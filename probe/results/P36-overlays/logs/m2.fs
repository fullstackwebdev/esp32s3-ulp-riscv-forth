1 SEG-BEGIN
: M ( -- ) 7 7 = IF ." HI " ELSE ." NO " THEN ;
' M SEG-ENTRY
1 SEG-SAVE
1 APP
." after" CR
