"""Auth domain — phone-number + OTP sign-in and PIN re-authentication.

To build. Rules (see ../../../CLAUDE.md): PINs hashed with Argon2id, never logged,
never recoverable (reset only via OTP); lock after repeated failures.
"""
