\ GUARDRAIL: an empty device group looks like a skipped group; write down WHY
\ it is empty (the words are primitives) or the next reader adds a wrapper to
\ fill it and pays 12 B for a call to an inlined primitive.
\ os_device.fs - P26 group 5: device words. Nothing to define, and that is
\ the finding. GPIO@ and GPIO! are primitives (P20 variant C PRIMS
\ X(GPIOG,..) X(GPIOS,..)), so the two words R1-R8 asks for cost 0 B of
\ Forth. ADC@ is a primitive too and is left where it is; MS and ADC@ are
\ not in R1-R8 and are not re-defined here. This group is 0 B: a wrapper
\ around a primitive would be padding, not a layer.
