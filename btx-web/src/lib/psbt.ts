/**
 * Minimal BIP-174 PSBT v0 builder for BTX fill transactions.
 *
 * Constructs a 2-input / 2-output draft PSBT given a server-side
 * Btx2FillDraft (the maker offer) and taker-side funding info
 * (UTXO, change address, fee). The result is base64 ready for the
 * connected wallet's signPsbt method.
 *
 * Layout:
 *   input[0]  = maker offer outpoint (NOT signed here; the maker
 *               supplies a SIGHASH_SINGLE|ANYONECANPAY pre-sig
 *               off-chain that the broadcast step will merge in)
 *   input[1]  = taker funding UTXO (the wallet signs this)
 *   output[0] = maker payout (total_sats to maker_payout_spk)
 *   output[1] = taker change (funding - total_sats - fee, to
 *               changeSpkHex)
 *
 * IMPORTANT: this is a taker-side draft. The output is NOT a fully
 * signed transaction. To broadcast, the maker's pre-sig must be
 * embedded at input[0] and the resulting tx finalized.
 *
 * The PSBT v0 binary spec is small enough to implement inline; no
 * bitcoinjs-lib dependency is added (every dep we ship is one we
 * can audit, and PSBT v0 hasn't changed in years).
 *
 * Refs:
 *   - BIP-174 (PSBT v0)
 *   - BIP-371 (Taproot PSBT fields — not used yet, taker funding
 *     assumed P2WPKH for now; can be extended later)
 *   - Bitcoin tx serialization format
 */

import type { Btx2FillDraft } from './api';

/** Magic bytes prefixing every PSBT: "psbt\xff". */
const PSBT_MAGIC = new Uint8Array([0x70, 0x73, 0x62, 0x74, 0xff]);

/** PSBT global key types. */
const PSBT_GLOBAL_UNSIGNED_TX = 0x00;
/** PSBT per-input key types. */
const PSBT_IN_SIGHASH_TYPE = 0x03;
/** Map separator (zero-length key). */
const PSBT_SEP = 0x00;

/**
 * Inputs the taker provides from their wallet to fund a fill tx.
 */
export interface TakerFunding {
  /** "txid:vout" of the taker's funding UTXO. */
  fundingOutpoint: string;
  /** Sats in the funding UTXO. */
  fundingValueSats: number;
  /** The taker's change scriptPubKey, hex-encoded. */
  changeSpkHex: string;
  /** Total fee in sats. Recipe: txVbytes × feerate. */
  feeSats: number;
  /** nSequence for inputs. Default RBF-enabled (0xfffffffd). */
  sequence?: number;
}

/** Structured result with the PSBT + the input index the wallet should sign. */
export interface BuiltFillPsbt {
  psbtBase64: string;
  /** Wallet should sign this input index only — the other is maker-side. */
  signInputIndexes: number[];
  /**
   * Change amount the taker receives back. Always positive (or zero);
   * the builder rejects construction when funding can't cover
   * total_sats + feeSats.
   */
  changeSats: number;
}

/**
 * Build a draft fill PSBT from a server-side Btx2FillDraft + taker
 * funding info. Throws on insufficient funding or malformed input.
 */
export function buildFillPsbt(
  draft: Btx2FillDraft,
  taker: TakerFunding,
): BuiltFillPsbt {
  const offer = parseOutpoint(draft.offer_input);
  const funding = parseOutpoint(taker.fundingOutpoint);

  if (taker.fundingValueSats < draft.total_sats + taker.feeSats) {
    throw new Error(
      `Funding insufficient: ${taker.fundingValueSats} sats < ${draft.total_sats + taker.feeSats} required (${draft.total_sats} to maker + ${taker.feeSats} fee).`,
    );
  }
  const changeSats =
    taker.fundingValueSats - draft.total_sats - taker.feeSats;

  const sequence = taker.sequence ?? 0xfffffffd;

  // Build the unsigned transaction body.
  const unsignedTx = serializeUnsignedTx({
    version: 2,
    inputs: [
      // input 0: maker offer outpoint — taker leaves it unsigned, the
      // maker's SIGHASH_SINGLE|ACP pre-sig is merged at broadcast.
      { prevTxid: offer.txid, vout: offer.vout, sequence },
      // input 1: taker funding UTXO — the connected wallet signs this.
      { prevTxid: funding.txid, vout: funding.vout, sequence },
    ],
    outputs: [
      // output 0: maker payout per the maker's pre-signed expectation.
      // The maker's SIGHASH_SINGLE binds input 0 to output 0, so this
      // ordering matters.
      { valueSats: draft.total_sats, scriptPubKeyHex: draft.maker_payout_spk_hex },
      // output 1: taker change.
      { valueSats: changeSats, scriptPubKeyHex: taker.changeSpkHex },
    ],
    locktime: 0,
  });

  // Assemble the PSBT (BIP-174 v0).
  const parts: Uint8Array[] = [];
  parts.push(PSBT_MAGIC);

  // Global map: just GLOBAL_UNSIGNED_TX.
  parts.push(keyValue(new Uint8Array([PSBT_GLOBAL_UNSIGNED_TX]), unsignedTx));
  parts.push(new Uint8Array([PSBT_SEP]));

  // Per-input map for input 0 (maker offer): sighash type 0x83.
  // Telling the wallet "if you choose to sign this, use SIGHASH_SINGLE|ACP".
  // In practice the wallet should skip input 0 entirely because the
  // maker's pre-sig already exists; we still set the hint for
  // correctness.
  parts.push(
    keyValue(
      new Uint8Array([PSBT_IN_SIGHASH_TYPE]),
      u32LE(draft.sighash_flag_for_offer_input),
    ),
  );
  parts.push(new Uint8Array([PSBT_SEP]));

  // Per-input map for input 1 (taker funding): empty.
  parts.push(new Uint8Array([PSBT_SEP]));

  // Per-output maps: both empty.
  parts.push(new Uint8Array([PSBT_SEP]));
  parts.push(new Uint8Array([PSBT_SEP]));

  const psbt = concatBytes(parts);
  return {
    psbtBase64: bytesToBase64(psbt),
    signInputIndexes: [1], // only the taker input
    changeSats,
  };
}

// ─── Tx serialization ───────────────────────────────────────────────

interface UnsignedTxInput {
  prevTxid: Uint8Array; // 32 bytes, little-endian on the wire
  vout: number;
  sequence: number;
}

interface UnsignedTxOutput {
  valueSats: number;
  scriptPubKeyHex: string;
}

interface UnsignedTx {
  version: number;
  inputs: UnsignedTxInput[];
  outputs: UnsignedTxOutput[];
  locktime: number;
}

function serializeUnsignedTx(tx: UnsignedTx): Uint8Array {
  const parts: Uint8Array[] = [];
  parts.push(u32LE(tx.version));
  parts.push(varint(tx.inputs.length));
  for (const i of tx.inputs) {
    parts.push(i.prevTxid); // already LE
    parts.push(u32LE(i.vout));
    parts.push(varint(0)); // empty scriptSig (unsigned)
    parts.push(u32LE(i.sequence));
  }
  parts.push(varint(tx.outputs.length));
  for (const o of tx.outputs) {
    parts.push(u64LE(o.valueSats));
    const spk = hexToBytes(o.scriptPubKeyHex);
    parts.push(varint(spk.length));
    parts.push(spk);
  }
  parts.push(u32LE(tx.locktime));
  return concatBytes(parts);
}

interface ParsedOutpoint {
  txid: Uint8Array;
  vout: number;
}

function parseOutpoint(s: string): ParsedOutpoint {
  const parts = s.split(':');
  if (parts.length !== 2) {
    throw new Error(`Outpoint expected "txid:vout", got "${s}".`);
  }
  const txidHexBE = parts[0];
  if (!/^[0-9a-fA-F]{64}$/.test(txidHexBE)) {
    throw new Error(`Outpoint txid must be 64 hex chars, got "${txidHexBE}".`);
  }
  const vout = Number(parts[1]);
  if (!Number.isInteger(vout) || vout < 0 || vout > 0xffffffff) {
    throw new Error(`Outpoint vout out of range: ${parts[1]}.`);
  }
  // Bitcoin display format is big-endian; on-wire format is little-endian.
  // Reverse byte order for serialization.
  const be = hexToBytes(txidHexBE);
  const le = new Uint8Array(32);
  for (let i = 0; i < 32; i++) le[i] = be[31 - i];
  return { txid: le, vout };
}

// ─── Byte helpers ──────────────────────────────────────────────────

function u32LE(n: number): Uint8Array {
  if (n < 0 || n > 0xffffffff) throw new Error(`u32 out of range: ${n}`);
  const b = new Uint8Array(4);
  b[0] = n & 0xff;
  b[1] = (n >>> 8) & 0xff;
  b[2] = (n >>> 16) & 0xff;
  b[3] = (n >>> 24) & 0xff;
  return b;
}

function u64LE(n: number): Uint8Array {
  // BTX values can exceed 2^53 in principle, but typical fill sizes
  // are well under that. We use Math.floor + bit math for the low 32
  // and Math.floor(n / 2^32) for the high 32 to stay within safe ints.
  if (n < 0 || n > Number.MAX_SAFE_INTEGER) {
    throw new Error(`u64 out of safe-integer range: ${n}`);
  }
  const b = new Uint8Array(8);
  const low = n >>> 0;
  const high = Math.floor(n / 0x1_0000_0000) >>> 0;
  b[0] = low & 0xff;
  b[1] = (low >>> 8) & 0xff;
  b[2] = (low >>> 16) & 0xff;
  b[3] = (low >>> 24) & 0xff;
  b[4] = high & 0xff;
  b[5] = (high >>> 8) & 0xff;
  b[6] = (high >>> 16) & 0xff;
  b[7] = (high >>> 24) & 0xff;
  return b;
}

/** Bitcoin varint encoding (compact size). */
function varint(n: number): Uint8Array {
  if (n < 0) throw new Error(`varint negative: ${n}`);
  if (n < 0xfd) return new Uint8Array([n]);
  if (n <= 0xffff) {
    const b = new Uint8Array(3);
    b[0] = 0xfd;
    b[1] = n & 0xff;
    b[2] = (n >>> 8) & 0xff;
    return b;
  }
  if (n <= 0xffffffff) {
    const b = new Uint8Array(5);
    b[0] = 0xfe;
    b[1] = n & 0xff;
    b[2] = (n >>> 8) & 0xff;
    b[3] = (n >>> 16) & 0xff;
    b[4] = (n >>> 24) & 0xff;
    return b;
  }
  // 8-byte form is unused for our sizes; keep the spec coverage.
  const b = new Uint8Array(9);
  b[0] = 0xff;
  b.set(u64LE(n), 1);
  return b;
}

function keyValue(key: Uint8Array, value: Uint8Array): Uint8Array {
  return concatBytes([varint(key.length), key, varint(value.length), value]);
}

function hexToBytes(hex: string): Uint8Array {
  if (hex.length % 2 !== 0) {
    throw new Error(`Hex length must be even, got ${hex.length}.`);
  }
  if (!/^[0-9a-fA-F]*$/.test(hex)) {
    throw new Error('Hex contains non-hex chars.');
  }
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

function concatBytes(parts: Uint8Array[]): Uint8Array {
  let total = 0;
  for (const p of parts) total += p.length;
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

function bytesToBase64(bytes: Uint8Array): string {
  let bin = '';
  for (let i = 0; i < bytes.length; i++) {
    bin += String.fromCharCode(bytes[i]);
  }
  if (typeof btoa === 'function') return btoa(bin);
  // Node fallback for SSR / tests.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const buf = (globalThis as any).Buffer;
  if (buf) return buf.from(bin, 'binary').toString('base64');
  throw new Error('No base64 encoder available.');
}
