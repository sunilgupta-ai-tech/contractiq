"""Phase 24: personal-data detection and masking, the ClamAV client, and the
document-level flag."""

import asyncio
import struct

import pytest

from app.core.config import Settings
from app.db.models import DocumentVersion
from app.schemas.document import DocumentVersionOut
from app.security.malware import (
    ClamAVScanner,
    ScannerUnavailableError,
    create_scanner,
    parse_reply,
)
from app.security.pii import find_pii, luhn_valid, mask_pii, pii_report, verhoeff_valid

AADHAAR = "234123412346"  # passes the Verhoeff check
CARD = "4111 1111 1111 1111"  # Visa test number, passes Luhn
# Built in two parts so secret scanners (gitleaks in CI) don't flag the test itself.
KEY_HEADER = "-----BEGIN RSA " + "PRIVATE KEY-----"
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


# --- Personal data -------------------------------------------------------------------


def test_checksums():
    assert verhoeff_valid(AADHAAR)
    assert not verhoeff_valid("234123412345")
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        (f"Aadhaar No. {AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}", "aadhaar", AADHAAR),
        (f"UID {AADHAAR}", "aadhaar", AADHAAR),
        ("PAN: ABCPE1234F", "pan", "ABCPE1234F"),
        (f"Card {CARD} exp 09/29", "card", "4111111111111111"),
        ("Write to Ravi.K@Example.co.in", "email", "ravi.k@example.co.in"),
        ("Mobile +91 98765 43210", "phone", "9876543210"),
        ("Call 09876543210", "phone", "9876543210"),
        ("US office +1 415 555 0100", "phone", "4155550100"),
        ("Bank A/c No. 0123 4567 8901 IFSC HDFC0001234", "bank_account", "012345678901"),
        ("Account number: 50100234567890", "bank_account", "50100234567890"),
        ("Passport No. K1234567 issued at Mumbai", "passport", "K1234567"),
        ("Pay via UPI ravi.k@okaxis today", "upi", "ravi.k@okaxis"),
        ("Login password: Tr0ub4dor&3", "secret", "Tr0ub4dor&3"),
        ("aws key AKIAIOSFODNN7EXAMPLE", "secret", "AKIAIOSFODNN7EXAMPLE"),
        (KEY_HEADER, "secret", KEY_HEADER),
    ],
)
def test_each_kind_is_found(text, kind, value):
    assert find_pii(text).get(kind) == {value}


@pytest.mark.parametrize(
    "text",
    [
        "Invoice 234123412345 dated 2026-09-27",  # 12 digits, fails Verhoeff
        "GSTIN 27ABCPE1234F1Z5",  # a company's tax id, not a person's PAN
        "Clause 12.3.4 applies; fees of 1,20,000 per annum",
        "Order ref 4111111111111112",  # fails Luhn
        "Account 12345678",
        "Invoice 501002345678 for order 98123",  # long number, but not labelled as an account
        "Passport photo and K1234567 reference",  # no number right after "passport"
        "The password policy requires 12 characters",
    ],
)
def test_ordinary_contract_numbers_are_not_personal_data(text):
    assert find_pii(text) == {}


def test_an_email_on_a_payment_domain_is_an_email_not_a_upi_id():
    assert set(find_pii("Email ravi@okaxis.com")) == {"email"}


def test_a_bank_account_is_not_also_counted_as_a_phone_number():
    assert set(find_pii("A/c No. 9876543210")) == {"bank_account"}


def test_a_card_is_not_also_counted_as_a_phone_number():
    assert set(find_pii(f"Card {CARD}")) == {"card"}


def test_report_counts_distinct_values_across_overlapping_chunks():
    chunks = ["Tenant PAN ABCPE1234F, mail a@x.in", "PAN ABCPE1234F again", "b@x.in"]
    assert pii_report(chunks) == {"types": {"email": 2, "pan": 1}, "total": 3}
    assert pii_report(["No personal data here."]) == {"types": {}, "total": 0}


def test_masking_keeps_the_last_four_digits_only():
    text = f"Aadhaar {AADHAAR}, card {CARD}, PAN ABCPE1234F"
    masked = mask_pii(text)
    assert AADHAAR not in masked and "1111 1111 1111 1111" not in masked
    assert "XXXX XXXX 2346" in masked and "•••• 1111" in masked
    assert "ABCPE1234F" in masked  # only Aadhaar and card numbers are masked
    assert mask_pii("Nothing to hide.") == "Nothing to hide."


def test_version_exposes_counts_never_values():
    version = DocumentVersion(extraction_metadata={"pii": {"types": {"aadhaar": 2}, "total": 2}})
    assert version.pii == {"aadhaar": 2}
    assert DocumentVersion(extraction_metadata={}).pii == {}
    assert DocumentVersionOut.model_fields["pii"].default == {}


# --- Malware scanning -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "clean", "signature"),
    [
        ("stream: OK", True, None),
        ("stream: Win.Test.EICAR_HDB-1 FOUND", False, "Win.Test.EICAR_HDB-1"),
    ],
)
def test_parse_reply(reply, clean, signature):
    result = parse_reply(reply)
    assert (result.clean, result.signature) == (clean, signature)


def test_an_error_reply_is_not_a_verdict():
    with pytest.raises(ScannerUnavailableError):
        parse_reply("INSTREAM size limit exceeded. ERROR")


async def _fake_clamd(received: list[bytes]):
    """Speaks clamd's INSTREAM protocol; reports EICAR as infected."""

    async def handle(reader, writer):
        assert await reader.readexactly(10) == b"zINSTREAM\0"
        body = b""
        while size := struct.unpack(">I", await reader.readexactly(4))[0]:
            body += await reader.readexactly(size)
        received.append(body)
        verdict = "Win.Test.EICAR_HDB-1 FOUND" if b"EICAR" in body else "OK"
        writer.write(f"stream: {verdict}\0".encode())
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def test_scanner_streams_bytes_and_files_in_chunks(tmp_path):
    received: list[bytes] = []
    server, port = await _fake_clamd(received)
    async with server:
        scanner = ClamAVScanner("127.0.0.1", port, timeout_s=5)
        assert (await scanner.scan(b"%PDF-1.7 clean")).clean
        infected = tmp_path / "eicar.pdf"
        infected.write_bytes(b"A" * (3 * 1024 * 1024) + EICAR)  # several chunks
        result = await scanner.scan(infected)
    assert not result.clean and result.signature == "Win.Test.EICAR_HDB-1"
    assert received[1] == infected.read_bytes()


async def test_unreachable_scanner_is_reported_not_treated_as_clean():
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    with pytest.raises(ScannerUnavailableError):
        await ClamAVScanner("127.0.0.1", port, timeout_s=2).scan(b"data")


def test_scanning_is_off_unless_configured():
    assert create_scanner(Settings()) is None
    assert isinstance(create_scanner(Settings(malware_scan="clamav")), ClamAVScanner)
