\ Regression: wild addresses must read as 0, never wrap a bound test (F-116).
\ `-1 @` used to pass `a + 1u < MEMSZ` because the sum wrapped to 0, then read mem-1.
-1 @ .
-1 c@ .
-1 w@ .
0 @ .
