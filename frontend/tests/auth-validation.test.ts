import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api-client";
import {
  fieldErrorsFromApi,
  passwordChecks,
  validateFullName,
  validateNewEmail,
  validateNewPassword,
  validateOrganization,
  validateSignInEmail,
  validateSignInPassword,
} from "@/utils/auth-validation";

// Same cases as backend/tests/unit/test_credentials.py, so the browser and
// the API agree on what is accepted.

describe("email", () => {
  it.each(["priya@acme.com", "  Priya.Sharma+legal@Acme.CO.IN ", "o'neil@example.org", "user@xn--80ak6aa92e.xn--p1ai"])(
    "accepts %s",
    (email) => expect(validateNewEmail(email)).toBeNull(),
  );

  it.each([
    "",
    "plainaddress",
    "@acme.com",
    "priya@",
    "priya@@acme.com",
    "priya@acme",
    "priya@acme.c",
    "priya@-acme.com",
    "priya@acme..com",
    ".priya@acme.com",
    "pri..ya@acme.com",
    "pri ya@acme.com",
    "priya@[127.0.0.1]",
    "a".repeat(65) + "@acme.com",
  ])("refuses %j", (email) => expect(validateNewEmail(email)).not.toBeNull());

  it("keeps sign-in loose so older accounts still work", () => {
    expect(validateSignInEmail(" Old@Acme.C ")).toBeNull();
    expect(validateSignInEmail("")).toBe("Enter your email address.");
    expect(validateSignInEmail("not-an-email")).toBe("Enter a valid email address.");
    expect(validateSignInPassword("")).toBe("Enter your password.");
  });
});

describe("names", () => {
  it("accepts real names in any script", () => {
    for (const name of ["Priya Sharma", "José Núñez", "प्रिया शर्मा"]) expect(validateFullName(name)).toBeNull();
    expect(validateOrganization("3M")).toBeNull();
  });

  it.each(["", "   ", "12345", "<b>Priya</b>", "Visit http://spam.example", "www.spam.in"])("refuses name %j", (name) =>
    expect(validateFullName(name)).not.toBeNull(),
  );

  it.each(["", "A", "--", "<Acme>", "x".repeat(201)])("refuses organization %j", (org) =>
    expect(validateOrganization(org)).not.toBeNull(),
  );
});

describe("password", () => {
  it.each(["correct horse battery staple", "Monsoon-train-7-mangoes", "जल्दी घर आओ भाई"])("accepts %s", (pw) =>
    expect(validateNewPassword(pw)).toBeNull(),
  );

  it.each([
    ["short pass", "at least 12"],
    ["x".repeat(73), "at most 72"],
    ["aaaaaaaaaaaa", "too few"],
    ["121212121212", "too few"],
    ["123456789012", "only numbers"],
    ["password1234", "too common"],
    ["Password@2026", "too common"],
    ["Welcome@2026", "too common"],
    ["qwertyuiop12", "too common"],
    ["abcdefghijklmn", "too common"],
    ["zyxwvutsrqpo", "too common"],
  ])("refuses %s (%s)", (pw, reason) => expect(validateNewPassword(pw)).toContain(reason));

  it("refuses passwords containing the person's own details", () => {
    const personal = ["priya.sharma@acme.com", "Priya Sharma", "Acme Legal"];
    for (const pw of ["priya-loves-mangoes", "i work at acme legal!", "sharma family 2026"]) {
      expect(validateNewPassword(pw, personal)).toBe("Password can't contain your email, name or organization name.");
    }
  });

  it("drives a live checklist", () => {
    expect(passwordChecks("").map((c) => c.ok)).toEqual([false, false, false]);
    expect(passwordChecks("password1234").map((c) => c.ok)).toEqual([true, false, true]);
    expect(passwordChecks("correct horse battery staple").every((c) => c.ok)).toBe(true);
  });
});

describe("API errors onto fields", () => {
  it("maps 422 field details and a taken email", () => {
    const invalid = new ApiError("The request is invalid.", "VALIDATION_ERROR", 422, null, {
      fields: [
        { loc: ["body", "email"], msg: "The part after @ isn't a valid domain, like company.com." },
        { loc: ["body", "password"], msg: "This password is too common. Choose something less predictable." },
      ],
    });
    expect(fieldErrorsFromApi(invalid)).toEqual({
      email: "The part after @ isn't a valid domain, like company.com.",
      password: "This password is too common. Choose something less predictable.",
    });
    const taken = new ApiError("An account with this email already exists.", "CONFLICT", 409, null);
    expect(fieldErrorsFromApi(taken)).toEqual({ email: "An account with this email already exists." });
    expect(fieldErrorsFromApi(new Error("x"))).toEqual({});
  });
});
