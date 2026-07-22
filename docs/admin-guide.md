# DRC Pay - Staff Guide

For the person who approves businesses and manages who else can do that.
You do not need to understand how the app is built to use this guide.

Everything here happens on one page: the **Staff page**.

---

## The three pages, and which one is yours

The app has three separate pages. They look similar, so it is worth knowing them apart.

| Page | Who it is for | Web address ends in |
|---|---|---|
| **Staff page** | **You.** Approve businesses, manage staff. | `/staff/` |
| Merchant page | Business owners. They take payments here. | `/console/` |
| Customer page | Shoppers paying a business. No sign-in. | `/customer/` |

**Your sign-in only works on the Staff page.** If you try it on the Merchant page it will say the
username or password is wrong. That is deliberate, not a fault: staff and business accounts are kept
completely separate, so neither can see the other's information.

---

## Signing in

Open the Staff page web address. You will be asked for a password **twice**, and they are different.

1. **A small box from your browser.** This is the shared site password that protects the whole
   demo site. Username: `drcpay`. Password: the shared site password.
2. **The page's own "Staff sign in" form.** This is *your* personal staff username and password.

If you only ever see the first box and never reach the sign-in form, you are on the wrong page or
the address is missing the `/staff/` ending.

---

## Approving a business

When a business signs up, it lands in a waiting state. Until you approve it, that business
**cannot sign in and cannot take any money.** Nothing happens automatically - it waits for you.

1. Sign in to the Staff page.
2. Look at **Merchant sign-ups**. The **Pending** tab is selected by default and shows everyone
   waiting.
3. Read the details for each one (see below).
4. Click **Approve** or **Reject**.

The list refreshes on its own, so a new sign-up appears within a few seconds without reloading.

### What each detail means

- **Business name** - what the owner typed when signing up. Nothing checks it, so read it critically.
- **Settles to** - the mobile money network and phone number where this business will receive its
  money. This is the important one.
- **Till code** - a short number the app assigns automatically. Customers can use it to pay from a
  basic phone. You do not choose it.
- The long code underneath (starting `m_`) is the app's internal identifier. Ignore it unless
  someone technical asks you for it.

### Before you approve, check

- Does the business name look like a real business, not a test or a joke?
- Does the phone number look right for the network shown next to it?
- Do you recognise this business, or did someone tell you to expect it?

Approving is what lets money start flowing to that phone number. If anything looks off, do not
approve it - ask first. Approving the wrong account is far more costly than making someone wait.

### What happens next

- **Approved** - they can sign in immediately and start taking payments. Nothing else is needed.
- **Rejected** - they stay locked out and cannot sign in.

**One important limitation:** rejecting is final from this page. Once you reject a business, the
Approve button is gone, and you cannot undo it yourself - someone technical has to reverse it.
**If you are unsure, leave it pending and ask.** A pending business is harmless; it simply waits.

---

## Adding another staff member

Anyone you add here can approve businesses, exactly like you. Only add people who should have that
power.

1. On the Staff page, find **Staff accounts**. It lists everyone who currently has access.
2. Click **Add a staff member**.
3. Enter a username and a password of at least 8 characters.
4. Click **Create staff account**.

They can sign in straight away, on the Staff page, with what you just set.

**Give them the password in person or through a private message - never by shared email or chat.**

If the username is already taken you will see "That username is already taken." Nothing is changed
when that happens; in particular, the existing person's password is left alone. Pick a different
username.

---

## Things this page cannot do yet

Ask someone technical for these:

- **Reset a forgotten staff password.**
- **Remove a staff member** who has left. (The app will refuse to remove the last remaining staff
  account, so there is always someone who can sign in.)
- **Undo a rejected business.**

The commands for these are in the appendix at the end, for whoever helps you.

---

## When something looks wrong

**A business says it cannot sign in.**
Check the **Approved** tab on the Staff page. If they are not there, look in **Pending** (they are
still waiting on you) or **Rejected** (they were turned down). Approving them fixes it.

**You cannot sign in yourself.**
Three usual causes, in order: you are on the Merchant page instead of the Staff page; the username
is typed with the wrong capital letters; or the password is genuinely wrong. Ask for a reset.

**A payment looks stuck.**
Payments confirm on their own, usually within seconds, and the app re-checks anything still waiting.
This is not something you need to fix from the Staff page.

**Someone you do not recognise appears in Staff accounts.**
Treat that seriously and raise it immediately - anyone listed there can approve businesses and so
can direct money to a phone number.

---

## Words you will see

- **Pending** - signed up, waiting for your decision, can do nothing yet.
- **Approved** (shown as *active*) - can sign in and take payments.
- **Rejected** - turned down, locked out.
- **Settles to** - the network and phone number where a business receives its money.
- **Till code** - the short number a customer can dial to pay a business from a basic phone.
- **Same-network payment** - when a customer pays a business on the same mobile money network, the
  money goes straight to the business and the *owner* confirms they received it. It never appears on
  your page.

---

## Appendix: for whoever helps you technically

These run against the deployed database and are not available in the browser.

Reset a password, or create an account outside the page:

    python -m drc_pay_api.create_staff --username NAME

Remove a staff member (refuses to remove the last remaining account, and signs them out everywhere):

    python -m drc_pay_api.create_staff --username NAME --remove

The first staff account on a brand-new deployment comes from the `DRCPAY_ADMIN_USERNAME` and
`DRCPAY_ADMIN_PASSWORD` settings. Changing the password setting and redeploying updates that same
account rather than creating a second one.

Reversing a rejected business currently has no command - it needs a direct call to the approve
endpoint or a database change.
