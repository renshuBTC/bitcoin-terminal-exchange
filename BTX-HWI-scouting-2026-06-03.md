# Scouting report — `bitcoin-core/HWI` (Andrew Chow's hardware-wallet interface)

*Eighth scouting target this 2026-06-03 cycle. Domain: hardware-wallet
device communication for PSBT signing.*

Date: 2026-06-03.

## Why this developer / repo

Andrew Chow (Ava Chow, @achow101) is a Bitcoin Core maintainer, the
author of BIP-380/381/382/383/384/385 (descriptors), and the principal
maintainer of HWI. HWI is the **canonical** Python library that lets
PSBT-based software talk to all major hardware wallets via a single
API: Trezor (One, Model T), Ledger (Nano S/X/S+), Coldcard, BitBox02,
Keepkey, Jade, Digital Bitbox.

For BTX, the question is whether HWI can give BTX a hardware-wallet
signing path. BTX's stance is "users bring their own wallet" — and
maker desks running real BTC balances will almost certainly want
hardware signing.

## Repository at a glance

Cloned to `Bitcoin CoreX/HWI-reference/`, master HEAD 2026-06-03.

```
hwilib/                              ~5,410 LOC core (MIT license)
  ├── commands.py     592 LOC        public API (enumerate, signtx, ...)
  ├── hwwclient.py    239 LOC        abstract HardwareWalletClient base
  ├── psbt.py        1158 LOC        full BIP-174 + BIP-371 PSBT parser
  ├── descriptor.py   639 LOC        descriptor parser (all types)
  ├── key.py          431 LOC        BIP-32 + key origin info
  ├── _serialize.py   258 LOC        compact-size + ser_string + uint256
  ├── tx.py           300 LOC        CTransaction / CTxIn / CTxOut
  ├── _base58.py      177 LOC        BIP-32 base58
  ├── _bech32.py      157 LOC        bech32 + bech32m
  ├── _script.py      155 LOC        script primitives
  ├── _cli.py         306 LOC        CLI entry-point
  ├── errors.py       247 LOC        error taxonomy
  ├── common.py        99 LOC        AddressType + Chain enums
  └── devices/                       vendor-specific clients
      ├── trezor.py + trezorlib/
      ├── ledger.py + ledger_bitcoin/
      ├── coldcard.py + ckcc/
      ├── bitbox02.py + bitbox02_lib/
      ├── jade.py + jadepy/
      ├── keepkey.py
      └── digitalbitbox.py

hwi.py                               CLI entry-point script
test/                                pytest harness with device emulators
test/data/test_psbt.json             official BIP-174 PSBT test vectors
```

## The clean public API

From `hwilib/commands.py` lines 103–199, verbatim:

> ```python
> def enumerate(password: Optional[str] = None, expert: bool = False,
>               chain: Chain = Chain.MAIN, allow_emulators: bool = False
>               ) -> List[Dict[str, Any]]:
>     """Enumerate all of the devices that HWI can potentially access."""
>
> def find_device(password=None, device_type=None, fingerprint=None,
>                 expert=False, chain=Chain.MAIN, allow_emulators=False
>                 ) -> Optional[HardwareWalletClient]:
>     """Find a device from the device type or fingerprint."""
>
> def signtx(client: HardwareWalletClient, psbt: str
>            ) -> Dict[str, Union[bool, str]]:
>     """Sign a Partially Signed Bitcoin Transaction (PSBT) with the client.
>     Returned as ``{"psbt": <base64 psbt string>, "signed": bool}``."""
> ```

And from `hwilib/hwwclient.py` line 232, verbatim:

> ```python
> def can_sign_taproot(self) -> bool:
>     """Whether the device has a version that can sign for Taproot inputs"""
> ```

Taproot signing is explicitly modelled as a capability flag. BTX's
envelope carrier is Taproot key-path, so this matters.

## Cross-validation against BTX's existing PSBT field constants

`hwilib/psbt.py` lines 100–105 define the BIP-371 input keytypes:

```python
PSBT_IN_TAP_KEY_SIG          = 0x13
PSBT_IN_TAP_SCRIPT_SIG       = 0x14
PSBT_IN_TAP_LEAF_SCRIPT      = 0x15
PSBT_IN_TAP_BIP32_DERIVATION = 0x16
PSBT_IN_TAP_INTERNAL_KEY     = 0x17
PSBT_IN_TAP_MERKLE_ROOT      = 0x18
```

These are **byte-for-byte identical** to the constants I shipped in
`btx_descriptor.py` last session for `encode_psbt_tap_internal_key_kv`
and `encode_psbt_tap_bip32_derivation_kv`. Independent confirmation
that BTX is BIP-371 compliant. (This is the second cross-validation
this scouting cycle — the first was pymatt's NUMS_KEY matching BTX's
vector 1.)

## BTX integration paths

### Path A — Subprocess call-out to the `hwi` CLI (simplest, ~30 LOC shim)

```python
# btx_hwi.py (NOT WRITTEN THIS SESSION — sketch only)
import json, subprocess
def enumerate_devices():
    out = subprocess.run(["hwi", "enumerate"], capture_output=True, check=True)
    return json.loads(out.stdout)

def sign_psbt(device_type: str, device_path: str, psbt_b64: str) -> str:
    out = subprocess.run(
        ["hwi", "--device-type", device_type, "--device-path", device_path,
         "signtx", psbt_b64], capture_output=True, check=True)
    return json.loads(out.stdout)["psbt"]
```

Pros: Zero new dependency in the BTX codebase. User installs HWI via
pip independently. The BTX bundle stays the same size.
Cons: Subprocess overhead per signing call. User must have `hwi` on
PATH.

### Path B — Library import (cleaner, requires bundle changes)

```python
from hwilib import commands as hwi
from hwilib.psbt import PSBT
client = hwi.find_device(device_type="trezor")
result = hwi.signtx(client, psbt_b64)
```

Pros: Direct Python API. Better error handling.
Cons: HWI brings ~12 vendor SDKs as transitive deps. Pulls in
`hidapi`, `libusb1`, `pyserial`, `cbor2`, `noiseprotocol`, `protobuf`,
`trezorlib`, etc. Significant packaging weight for the BTX bundle.

### Path C — Use HWI's `psbt.py` as a cross-validation oracle

BTX has its own minimal PSBT support (only what's needed for BIP-371
TAP fields). HWI's `psbt.py` is a full round-trip implementation.

A test in `btx_xtest_suite.py` could:
1. Build a BTX2 order PSBT via existing BTX primitives
2. Parse the bytes through `hwilib.psbt.PSBT().deserialize(...)`
3. Confirm round-trip equivalence and field correctness

This is the **same pattern** as the rust-miniscript cross-validation
that surfaced the descriptor checksum bug last session. It would
catch any future BIP-174 / BIP-371 emission bugs in BTX before they
hit hardware-wallet users.

## Why no code lands this session

Three honest reasons:

1. **No live test target.** Hardware-wallet integration is
   unverifiable without either real hardware or vendor emulators
   (trezor-emulator, ledger-speculos). Shipping a `btx_hwi.py` shim
   that's never been run end-to-end would be unverified integration
   code — explicitly against the user's stated preference: *"Never
   guess or fabricate information just to be helpful."*

2. **No current product driver.** BTX has one user (Renshu) on
   `RenshuBTC` mainnet wallet. No maker desk is asking for hardware
   signing today. Path B's bundle weight is hard to justify
   speculatively.

3. **Cross-validation via Path C is small but unfocused.** A
   `psbt_roundtrip_vs_hwi` sub-test would require either bundling HWI
   into the watcher's sandbox or installing it via pip (which works
   but adds CI weight for a check that today's BIP-371 constants
   already cross-validate by inspection).

The honest decision is: **bookmark all three paths**, ship none.

## Trigger conditions for revisiting

| Trigger | Path to take |
|---------|--------------|
| First maker desk requests hardware signing | Path A (subprocess shim) — minimal change |
| BTX bundle adds a "Pro" user tier | Path B (library import) — first-class hardware support |
| A BIP-371 emission bug is suspected | Path C (cross-validation) — quick standalone xtest |

## Pattern across 8 scouts this cycle

| Repo | Outcome | Reason |
|------|---------|--------|
| `secp256k1-zkp` | shipped (primitive) | direct primitive fit |
| `secp256kfun` | shipped (FROST) + specced (DLEQ) | primitive fit + design extraction |
| `bitcoin/bips` | shipped (BIP-374 DLEQ) | primitive port |
| `rust-miniscript` | shipped (descriptors) | found fit after deeper read |
| `sipa/minisketch` | spec only | build-deps blocker (operational) |
| `mit-dci/utreexo` | spec only | no UTXO use case (architectural) |
| `Merkleize/pymatt` | spec only | CCV not on mainnet (consensus) |
| **`bitcoin-core/HWI`** | **spec only** | **no hardware test target (product)** |

Effective extraction rate: **4/8 = 50%**. The deferred half splits
cleanly by reason category: 1 operational, 1 architectural, 1
consensus-dependent, 1 product-driven. None are due to the repo being
low-quality — every scouting target this cycle has been a serious,
well-engineered project.

## Small cross-validation finding

HWI's BIP-371 PSBT field constants (`PSBT_IN_TAP_KEY_SIG = 0x13` through
`PSBT_IN_TAP_MERKLE_ROOT = 0x18`) are byte-identical to BTX's. This
confirms BTX is on the canonical wire format. Not a discovery — the
BIP defines these values — but an independent cross-check that BTX
implemented them correctly.

## File index

```
Bitcoin CoreX/HWI-reference/                                 (cloned 2026-06-03)
  ├── hwilib/                                                ~5,410 LOC core
  ├── devices/{trezor,ledger,coldcard,bitbox02,jade,...}     vendor SDKs
  ├── test/data/test_psbt.json                               BIP-174 vectors
  └── README.md                                              install + usage

bitcoin-terminal-exchange/
  └── BTX-HWI-scouting-2026-06-03.md                         (THIS DOC)
```

## Source

Repo: <https://github.com/bitcoin-core/HWI>
Author: Ava Chow (@achow101) and contributors
License: MIT
Examined: master HEAD at clone time 2026-06-03. Version 3.2.0 per
`pyproject.toml`.
Production reference: Bitcoin Core's `hwi` integration as well as
Sparrow Wallet, BlueWallet, Electrum, Specter Desktop.
