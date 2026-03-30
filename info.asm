; For all points we do not store the direct (x,y)
; x,y coordinates but an index into the x_coord 
; and y_coord list , this way we need much less calculations
;
; As an other speedup trick we made sure that if a value is both in the X_coord
; list and y_coordlist, we placed them in the front of both lists with the same
; index, so that we only have to calculate sin and cos once and then can copy
; them to the other list :-)



x_coord	ds 256
y_coord	ds 256
x_cos	ds 512
x_sin	ds 512
y_cos	ds 512
y_sin	ds 512
x_final	ds 512
y_final	ds 512
clip_check	ds 256

