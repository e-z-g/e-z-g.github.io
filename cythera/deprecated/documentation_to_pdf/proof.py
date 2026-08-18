import sys, pymupdf, os
src=sys.argv[1]; out=sys.argv[2]; cols=int(sys.argv[3]) if len(sys.argv)>3 else 6
os.makedirs(out, exist_ok=True)
d=pymupdf.open(src)
from PIL import Image
thumbs=[]
for i,pg in enumerate(d):
    pm=pg.get_pixmap(dpi=100)
    p='%s/p%02d.png'%(out,i+1); pm.save(p); thumbs.append(p)
# contact sheet
ims=[Image.open(t) for t in thumbs]
tw,th=ims[0].size; sc=260/tw; tw,th=int(tw*sc),int(th*sc)
rows=(len(ims)+cols-1)//cols
sheet=Image.new('RGB',(cols*tw+ (cols+1)*8, rows*(th+16)+8),'#888')
from PIL import ImageDraw
dr=ImageDraw.Draw(sheet)
for i,im in enumerate(ims):
    r,cc=divmod(i,cols)
    x=8+cc*(tw+8); y=8+r*(th+16)
    sheet.paste(im.resize((tw,th)),(x,y))
    dr.text((x+2,y+th+2),'p%d'%(i+1),fill='white')
sheet.save(out+'/sheet.png')
print('pages',len(ims),'->',out+'/sheet.png')
