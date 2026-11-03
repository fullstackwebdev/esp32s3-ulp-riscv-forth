# Notice

This repository is research: measurements taken on hardware owned by the author.

* **Licence.** Our code and prose are MIT (see `LICENSE`). Third-party material is not covered and is not vendored
  here — see `docs/SHARING.md` for what is deliberately excluded and how to fetch it.
* **Radio scope.** Every transmission and reception described here happened between boards on the author's desk. No
  third-party network, API, backend or device was probed. Meshtastic protocol facts were obtained from a stock node's
  own over-the-air emissions and from its published source.
* **Not a product.** In particular the Meshtastic interoperability is **one-directional and unfinished**: our stack
  receives from a stock node but no stock node has ever decoded our transmissions. `docs/32-handoff-meshtastic-interop.md`
  is the precise state, including everything that was tried and failed.
* **Safety.** Raw flash dumps are deliberately not published because they carry per-device private keys; flash your own
  boards from your own dumps. Configuration values quoted in the docs (channel PSK, sync word, carrier) are the public
  Meshtastic defaults, reproduced as measured facts.
