\ os_events.fs - P26 group 2: one 4-cell ring, one registration kind (pin).
\ GUARDRAIL: an entry is a bare handler xt with no payload, so POLL-EVENTS
\ dispatches with @ EXECUTE and needs no per-kind compare. P24 carried a
\ kind cell and its POLL-EVENTS measured 320 B; the payload-free entry is
\ the cut that brings the dispatch path into one page.
CREATE RING 16 ALLOT
CREATE RN 0 ,              \ entries queued
CREATE PIN 0 ,             \ registered pin number
CREATE PXT 0 ,             \ registered handler xt

: ON-EVENT   PXT ! PIN ! ; \ ( pin xt -- ) register the pin handler

\ POST ( xt -- ) append one event. A full ring is a named error, not a
\ clamp: the event is dropped and DIAG = 1, which is the only reachable
\ path to the REPL's error report.
: POST
  RN @ 4 < IF
    RN @ 4 * RING + !
    RN @ 1+ RN !
  ELSE DROP 1 DIAG ! THEN ;

\ POLL-EVENTS : sample the registered pin (level triggered, not edge:
\ there is no second cell to remember the last level), then drain the ring
\ top first. Always returns.
: POLL-EVENTS
  PIN @ GPIO@ IF PXT @ POST THEN
  RN @ 0 DO
    RN @ 1- DUP RN ! 4 * RING + @ EXECUTE
  LOOP ;
