import { derived, writable } from 'svelte/store'

// Bilingual FR/EN, French default (this is the DRC). Strings are ported faithfully from the
// live console (frontend/merchant-console) so the two read the same, plus the new-shell keys
// (nav, greeting, charge sheet). Switching language re-renders everything: components read `$t`.

export type Lang = 'fr' | 'en'
const KEY = 'interpay.lang'

function initial(): Lang {
  const saved = localStorage.getItem(KEY)
  return saved === 'en' ? 'en' : 'fr' // anything not "en" (incl. unset) → French
}

export const lang = writable<Lang>(initial())

lang.subscribe((l) => {
  document.documentElement.setAttribute('lang', l)
  try {
    localStorage.setItem(KEY, l)
  } catch {
    /* private mode - the attribute still applies for this session */
  }
})

export const setLang = (l: Lang) => lang.set(l)
export const toggleLang = () => lang.update((l) => (l === 'fr' ? 'en' : 'fr'))

// Transaction state → short human label (feed pills, charge sheet).
type StateDict = Record<string, string>

interface Strings {
  // shell / nav
  logout: string
  nav_overview: string
  nav_payments: string
  nav_customers: string
  nav_settings: string
  tab_home: string
  tab_charge: string
  // login
  login_title: string
  login_sub: string
  login_user: string
  login_pass: string
  login_btn: string
  login_busy: string
  login_err: string
  login_unreachable: string
  login_demo: string
  // overview header
  greet: (name: string) => string
  settles_to: (op: string, msisdn: string) => string
  // take a payment
  take_h2: string
  take_tag: string
  amount_label: string
  show_qr: string
  feature_phone: string
  take_fine: string
  // charge sheet
  charge_title: string
  charge_show: (amount: string) => string
  charge_waiting: string
  charge_paid: string
  charge_declined: string
  charge_refunded: string
  charge_review: string
  charge_done: string
  charge_cancel: string
  // dial code card
  dial_h2: string
  dial_print: string
  dial_fine: string
  // recent payments
  feed_h2: string
  feed_view_all: string
  feed_empty: string
  feed_loading: string
  confirm_receipt: string
  confirm_received: string
  not_received: string
  confirm_from: (msisdn: string, op: string) => string
  paid: string
  // errors
  err_api: string
  retry: string
  // nested
  states: StateDict
  charge_states: StateDict
}

const en: Strings = {
  logout: 'Log out',
  nav_overview: 'Overview',
  nav_payments: 'Payments',
  nav_customers: 'Customers',
  nav_settings: 'Settings',
  tab_home: 'Home',
  tab_charge: 'Charge',
  login_title: 'Sign in',
  login_sub: 'Sign in with your merchant account. You only ever see your own payments.',
  login_user: 'Username',
  login_pass: 'Password',
  login_btn: 'Log in',
  login_busy: 'Signing in…',
  login_err: 'Invalid username or password.',
  login_unreachable: "Couldn't reach the server. Check your connection and try again.",
  login_demo: 'Demo accounts - one tap signs you in:',
  greet: (name) => `Good morning, ${name}`,
  settles_to: (op, msisdn) => `settling to ${op} · ${msisdn}`,
  take_h2: 'Take a payment',
  take_tag: 'smartphone',
  amount_label: 'Amount',
  show_qr: 'Show QR to charge',
  feature_phone: 'Feature phone · no internet',
  take_fine: 'The customer scans and pays exactly this amount. Confirms in seconds.',
  charge_title: 'Scan to pay',
  charge_show: (amount) => `Show this QR to the customer to collect ${amount}.`,
  charge_waiting: 'Waiting for payment…',
  charge_paid: 'Paid',
  charge_declined: 'Declined - the customer can try again.',
  charge_refunded: 'Refunded',
  charge_review: 'Needs review',
  charge_done: 'Done',
  charge_cancel: 'Cancel',
  dial_h2: 'Your dial code',
  dial_print: 'Print',
  dial_fine: 'Tape it up. Any phone can dial it - no app, no internet.',
  feed_h2: 'Recent payments',
  feed_view_all: 'View all',
  feed_empty: 'No payments yet - take one above.',
  feed_loading: 'Loading payments…',
  confirm_receipt: 'Confirm receipt',
  confirm_received: 'Confirm received',
  not_received: 'Not received',
  confirm_from: (msisdn, op) => `from ${msisdn} · ${op}`,
  paid: 'Paid',
  err_api: "Couldn't reach the server.",
  retry: 'Retry',
  states: {
    initiated: 'Starting',
    collection_pending: 'Awaiting payment',
    collection_succeeded: 'Received',
    payout_pending: 'Settling',
    payout_succeeded: 'Paid',
    payout_failed: 'Settle failed',
    refund_pending: 'Refunding',
    refunded: 'Refunded',
    collection_failed: 'Declined',
    manual_review: 'Needs review',
  },
  charge_states: {
    awaiting_payment: 'Awaiting payment',
    processing: 'Processing…',
    paid: 'Paid',
    declined: 'Declined',
    refunded: 'Refunded',
    review: 'Needs review',
  },
}

const fr: Strings = {
  logout: 'Déconnexion',
  nav_overview: 'Accueil',
  nav_payments: 'Paiements',
  nav_customers: 'Clients',
  nav_settings: 'Réglages',
  tab_home: 'Accueil',
  tab_charge: 'Encaisser',
  login_title: 'Connexion',
  login_sub: 'Connectez-vous avec votre compte marchand. Vous ne voyez que vos propres paiements.',
  login_user: "Nom d'utilisateur",
  login_pass: 'Mot de passe',
  login_btn: 'Se connecter',
  login_busy: 'Connexion…',
  login_err: "Nom d'utilisateur ou mot de passe invalide.",
  login_unreachable: 'Impossible de joindre le serveur. Vérifiez votre connexion et réessayez.',
  login_demo: 'Comptes démo - un clic pour se connecter :',
  greet: (name) => `Bonjour, ${name}`,
  settles_to: (op, msisdn) => `règlement vers ${op} · ${msisdn}`,
  take_h2: 'Encaisser un paiement',
  take_tag: 'smartphone',
  amount_label: 'Montant',
  show_qr: 'Afficher le QR',
  feature_phone: 'Téléphone basique · sans internet',
  take_fine: 'Le client scanne et paie exactement ce montant. Confirmation en quelques secondes.',
  charge_title: 'Scanner pour payer',
  charge_show: (amount) => `Montrez ce QR au client pour encaisser ${amount}.`,
  charge_waiting: 'En attente du paiement…',
  charge_paid: 'Payé',
  charge_declined: 'Refusé - le client peut réessayer.',
  charge_refunded: 'Remboursé',
  charge_review: 'À vérifier',
  charge_done: 'Terminé',
  charge_cancel: 'Annuler',
  dial_h2: 'Votre code à composer',
  dial_print: 'Imprimer',
  dial_fine: "Affichez-le. N'importe quel téléphone peut le composer - sans appli ni internet.",
  feed_h2: 'Paiements récents',
  feed_view_all: 'Voir tout',
  feed_empty: 'Aucun paiement pour l’instant - encaissez-en un ci-dessus.',
  feed_loading: 'Chargement des paiements…',
  confirm_receipt: 'Confirmer la réception',
  confirm_received: 'Confirmer la réception',
  not_received: 'Non reçu',
  confirm_from: (msisdn, op) => `de ${msisdn} · ${op}`,
  paid: 'Payé',
  err_api: 'Impossible de joindre le serveur.',
  retry: 'Réessayer',
  states: {
    initiated: 'Démarrage',
    collection_pending: 'En attente de paiement',
    collection_succeeded: 'Reçu',
    payout_pending: 'Règlement…',
    payout_succeeded: 'Payé',
    payout_failed: 'Échec règlement',
    refund_pending: 'Remboursement…',
    refunded: 'Remboursé',
    collection_failed: 'Refusé',
    manual_review: 'À vérifier',
  },
  charge_states: {
    awaiting_payment: 'En attente de paiement',
    processing: 'En cours…',
    paid: 'Payé',
    declined: 'Refusé',
    refunded: 'Remboursé',
    review: 'À vérifier',
  },
}

const DICT: Record<Lang, Strings> = { fr, en }

/** Reactive translations. In a component: `$t.take_h2`, `$t.greet(name)`, `$t.states[state]`. */
export const t = derived(lang, ($lang) => DICT[$lang])
