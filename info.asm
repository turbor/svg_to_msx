; The pseudocode
; The mainlus is can be described in this pseudcode

Get new middlepoint (x,y) and rotation_angle (alpha)
if new_alpha != old_alpha:
    fetch cos and sine for alpha
    recalculate all x_cos,x_sin
    copy shared x_cos,x_sin to y_cos,y_sin
    recalculate remaining y_cos,y_sin
if (new_midpoint!=old_midpoint) or (new_alpha != old_alpha):
    for all points
        calculate x_final
        calculate y_final
        calculate clip_check
for all path in paths:
  p1=first point of path
  for i=1;i<len(path)-1;i++
    p2=point i of path
    if (clip_check(p1) || clip_check(p2))==0:
      #trivial draw since both in screen
      draw line from p1 to p2

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

