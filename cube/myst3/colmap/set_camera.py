"""Set every camera's parameters in a COLMAP database (and mark them as known).

    python set_camera.py DATABASE.db 455,320,180

Used to try a movie at several fixed focal lengths on the same features and matches."""
import sqlite3, sys, numpy as np
db = sqlite3.connect(sys.argv[1]); params = [float(v) for v in sys.argv[2].split(',')]
db.execute('update cameras set params = ?, prior_focal_length = 1', (np.array(params, np.float64).tobytes(),))
db.commit(); print('cameras set to', params, db.execute('select count(*) from cameras').fetchone()[0], 'camera(s)')
