// ============================================================================
// Cubemap atlas layout — the contract between stitcher.html and index.html.
//
// Both pages import this module. Nothing else defines the layout, because the
// two sides have to agree exactly: the stitcher writes cells at particular
// rotations and the viewer's sampleAtlas() reads them back on that assumption.
// Change one without the other and the poles smear, silently.
//
// ---------------------------------------------------------------------------
// Face indices
//
// The viewer's cube is a BoxGeometry scaled by (-1, 1, 1), so its six material
// slots — which are also the `uFace` uniform — cover these directions:
//
//   0: -X    1: +X    2: +Y    3: -Y    4: +Z    5: -Z
//
// gnomonicUV() in the viewer maps a direction to that face's [0,1] UV. The
// inverse (faceUvToDir) and the forward projection (dirToFaceUv) live here so
// the stitcher can resample across face boundaries when building gutters.
//
// ---------------------------------------------------------------------------
// Face names are pinned to the working separate-image path
//
// The viewer's separate-image path (getCubemapUrls) hands its six URLs to the
// material slots in the order [left, right, top, bottom, back, front], and the
// built-in locations render correctly, so that is the authoritative meaning of
// each name: left = slot 0, right = 1, top = 2, bottom = 3, back = 4, front = 5.
//
// The stitcher's cell labels used to disagree — its "Left" cell was the one slot
// 1 (+X, the right-hand face) reads, and likewise front/back were transposed.
// Placing files by those labels built a cube whose wall ring was yawed 180
// degrees while the poles were not, so the walls no longer met top and bottom.
// The labels below are corrected to match the separate-image path; the cell
// *geometry* is untouched, so the fix is a relabelling, not a format change.
// Verified by diffing a stitched atlas against the built-in Amateria rendering,
// which has no depth and therefore a fixed, reproducible camera.
// ============================================================================

export const FACES = ['left', 'front', 'right', 'back', 'top', 'bottom'];

export const FACE_LABELS = {
  left:  'Left (−X)',  front: 'Front (−Z)',
  right: 'Right (+X)', back:  'Back (+Z)',
  top:   'Top (+Y)',   bottom:'Bottom (−Y)'
};

// Face name -> viewer material index. Matches getCubemapUrls' ordering.
export const FACE_INDEX = { left: 0, right: 1, top: 2, bottom: 3, back: 4, front: 5 };
export const INDEX_FACE = Object.fromEntries(Object.entries(FACE_INDEX).map(([k, v]) => [v, k]));

// ---------------------------------------------------------------------------
// Layouts
// ---------------------------------------------------------------------------
//
// 5x3 — the original. 15 cells for 6 faces: the top face appears five times and
// the bottom face five times, each rotated so that its cell's neighbour in the
// atlas is the wall it is genuinely adjacent to. That redundancy is what buys
// correct bilinear filtering at the pole edges; sampleAtlas() blends the four
// rotated copies by quadrant, and because each copy is rotated back by
// rotateUV() they agree everywhere except at those edges.
//
// 3x2 — compact. 6 cells for 6 faces, so 60% fewer pixels at the same face
// resolution, one texture fetch per fragment instead of up to four at the
// poles, and a higher usable face size under the browser's canvas area cap.
// It replaces the duplication with a baked gutter: each cell reserves a border
// of GUTTER_PX pixels filled by resampling the neighbouring faces, and the
// viewer insets its UVs by the same fraction. Same effect, a fraction of the
// pixels.

export const GUTTER_PX = 8;

export const LAYOUTS = {
  '5x3': {
    id: '5x3', cols: 5, rows: 3, aspect: 5 / 3, gutter: 0,
    label: '5×3 (pole-duplicated)',
    note: 'Original format. Larger, but needs no gutter.',
    // Cell order is row-major from the top-left of the image.
    cells: [
      { face: 'top',    rot: -90, note: 'Top\n-90°' },
      { face: 'top',    rot:   0, note: 'Top\n0°'   },
      { face: 'top',    rot:  90, note: 'Top\n+90°' },
      { face: 'top',    rot: 180, note: 'Top\n180°' },
      { face: 'top',    rot: -90, note: 'Top\ndup'  },
      // Column order follows sampleAtlas below: col0 is read by slot 1 (right),
      // col1 by slot 4 (back), col2 by slot 0 (left), col3 by slot 5 (front).
      { face: 'right',  rot:   0, note: 'Right' },
      { face: 'back',   rot:   0, note: 'Back'  },
      { face: 'left',   rot:   0, note: 'Left'  },
      { face: 'front',  rot:   0, note: 'Front' },
      { face: 'right',  rot:   0, note: 'R dup' },
      { face: 'bottom', rot:  90, note: 'Bot\n+90°' },
      { face: 'bottom', rot:   0, note: 'Bot\n0°'   },
      { face: 'bottom', rot: -90, note: 'Bot\n-90°' },
      { face: 'bottom', rot: 180, note: 'Bot\n180°' },
      { face: 'bottom', rot:  90, note: 'Bot\ndup'  },
    ],
  },
  '3x2': {
    id: '3x2', cols: 3, rows: 2, aspect: 3 / 2, gutter: GUTTER_PX,
    label: '3×2 (compact)',
    note: 'No duplication; edges filled by a resampled gutter.',
    cells: [
      { face: 'left',   rot: 0, note: 'Left'   },
      { face: 'front',  rot: 0, note: 'Front'  },
      { face: 'right',  rot: 0, note: 'Right'  },
      { face: 'back',   rot: 0, note: 'Back'   },
      { face: 'top',    rot: 0, note: 'Top'    },
      { face: 'bottom', rot: 0, note: 'Bottom' },
    ],
  },
};

// Which cell index holds a given face, for layouts without duplication.
export function cellIndexOfFace(layout, face) {
  return layout.cells.findIndex(c => c.face === face);
}

// Pick a layout from an image's dimensions. 5:3 is 1.667, 3:2 is 1.5.
export function detectLayout(width, height) {
  const aspect = width / height;
  let best = null, bestErr = Infinity;
  for (const l of Object.values(LAYOUTS)) {
    const err = Math.abs(aspect - l.aspect) / l.aspect;
    if (err < bestErr) { bestErr = err; best = l; }
  }
  // Beyond a few percent it is not one of ours; caller decides what to do.
  return bestErr <= 0.04 ? best : null;
}

// ---------------------------------------------------------------------------
// Projection, shared by the viewer's shader and the stitcher's gutter builder
// ---------------------------------------------------------------------------

// These must stay the exact inverse/forward of gnomonicUV in index.html. u runs
// with increasing yaw on all four walls; faces 2, 3, 4 and 5 take -x, not +x.
// (They were written against an earlier gnomonicUV that had ±Z mirrored.)

// Face-local UV in [0,1] -> unnormalised direction. Inverse of gnomonicUV.
export function faceUvToDir(faceIndex, u, v) {
  const a = u * 2 - 1, b = v * 2 - 1;
  switch (faceIndex) {
    case 0: return [-1,  b, -a];
    case 1: return [ 1,  b,  a];
    case 2: return [-a,  1, -b];
    case 3: return [-a, -1,  b];
    case 4: return [-a,  b,  1];
    default:return [ a,  b, -1];
  }
}

// Project a direction onto one specific face, whether or not it belongs there.
export function projectOntoFace(faceIndex, x, y, z) {
  let a, b, m;
  switch (faceIndex) {
    case 0:  m = Math.abs(x); a = -z / m; b =  y / m; break;
    case 1:  m = Math.abs(x); a =  z / m; b =  y / m; break;
    case 2:  m = Math.abs(y); a = -x / m; b = -z / m; break;
    case 3:  m = Math.abs(y); a = -x / m; b =  z / m; break;
    case 4:  m = Math.abs(z); a = -x / m; b =  y / m; break;
    default: m = Math.abs(z); a =  x / m; b =  y / m; break;
  }
  return { u: a * 0.5 + 0.5, v: b * 0.5 + 0.5 };
}

// Direction -> { faceIndex, u, v }. Forward gnomonic projection.
export function dirToFaceUv(x, y, z) {
  const ax = Math.abs(x), ay = Math.abs(y), az = Math.abs(z);
  let faceIndex;
  if (ax >= ay && ax >= az) faceIndex = x < 0 ? 0 : 1;
  else if (ay >= az)        faceIndex = y > 0 ? 2 : 3;
  else                      faceIndex = z > 0 ? 4 : 5;
  return { faceIndex, ...projectOntoFace(faceIndex, x, y, z) };
}

// ---------------------------------------------------------------------------
// GLSL
// ---------------------------------------------------------------------------

const GLSL_HELPERS = `
  vec2 rotateUV(vec2 uv, float angleDeg) {
    float a = radians(angleDeg); float s = sin(a), c = cos(a);
    vec2 p = uv - 0.5; return vec2(p.x * c - p.y * s, p.x * s + p.y * c) + 0.5;
  }
`;

const GLSL_5X3 = `
  vec2 getGrid(float col, float row, vec2 localUv) { return vec2((col + localUv.x) / 5.0, (2.0 - row + localUv.y) / 3.0); }
  vec4 sampleAtlas(sampler2D tex, int face, vec2 local) {
    if (face == 4) return texture2D(tex, getGrid(1.0, 1.0, local));
    if (face == 0) return texture2D(tex, getGrid(2.0, 1.0, local));
    if (face == 5) return texture2D(tex, getGrid(3.0, 1.0, local));

    if (face == 1) {
      vec4 c4 = texture2D(tex, getGrid(4.0, 1.0, local));
      vec4 c0 = texture2D(tex, getGrid(0.0, 1.0, local));
      return mix(c4, c0, smoothstep(0.25, 0.75, local.x));
    }

    // Pole faces: blend the four rotated copies by quadrant, so the bilinear
    // neighbour at each edge is the wall that edge actually adjoins.
    float d1 = local.x - local.y;
    float d2 = (1.0 - local.x) - local.y;
    float t1 = smoothstep(-0.1, 0.1, d1);
    float t2 = smoothstep(-0.1, 0.1, d2);

    float wBottom = t1 * t2;
    float wTop    = (1.0 - t1) * (1.0 - t2);
    float wLeft   = (1.0 - t1) * t2;
    float wRight  = t1 * (1.0 - t2);

    if (face == 2) {
      vec4 cFront = texture2D(tex, getGrid(1.0, 0.0, local));
      vec4 cBack  = texture2D(tex, getGrid(3.0, 0.0, rotateUV(local, 180.0)));
      vec4 cLeft  = texture2D(tex, getGrid(0.0, 0.0, rotateUV(local, 90.0)));
      vec4 cRight = texture2D(tex, getGrid(2.0, 0.0, rotateUV(local, -90.0)));
      return cFront * wBottom + cBack * wTop + cLeft * wLeft + cRight * wRight;
    }

    if (face == 3) {
      vec4 cFront = texture2D(tex, getGrid(1.0, 2.0, local));
      vec4 cBack  = texture2D(tex, getGrid(3.0, 2.0, rotateUV(local, 180.0)));
      vec4 cLeft  = texture2D(tex, getGrid(0.0, 2.0, rotateUV(local, -90.0)));
      vec4 cRight = texture2D(tex, getGrid(2.0, 2.0, rotateUV(local, 90.0)));
      return cFront * wTop + cBack * wBottom + cLeft * wLeft + cRight * wRight;
    }
    return vec4(0.0);
  }
`;

// GUTTER_FRAC is filled in per atlas, since it depends on the face size the
// atlas was written at.
const GLSL_3X2 = `
  uniform float uGutterFrac;
  vec2 getGrid(float col, float row, vec2 localUv) { return vec2((col + localUv.x) / 3.0, (1.0 - row + localUv.y) / 2.0); }
  vec4 sampleAtlas(sampler2D tex, int face, vec2 local) {
    // Inset into the cell's content area; the border is neighbour bleed.
    // Cell order is left, front, right / back, top, bottom — matching FACE_INDEX.
    vec2 inset = mix(vec2(uGutterFrac), vec2(1.0 - uGutterFrac), local);
    if (face == 0) return texture2D(tex, getGrid(0.0, 0.0, inset));  // left
    if (face == 5) return texture2D(tex, getGrid(1.0, 0.0, inset));  // front
    if (face == 1) return texture2D(tex, getGrid(2.0, 0.0, inset));  // right
    if (face == 4) return texture2D(tex, getGrid(0.0, 1.0, inset));  // back
    if (face == 2) return texture2D(tex, getGrid(1.0, 1.0, inset));  // top
    return texture2D(tex, getGrid(2.0, 1.0, inset));                 // bottom
  }
`;

export function sampleAtlasGlsl(layoutId) {
  return GLSL_HELPERS + (layoutId === '3x2' ? GLSL_3X2 : GLSL_5X3);
}

// True when the layout's shader declares a uGutterFrac uniform.
export function layoutUsesGutter(layoutId) {
  return layoutId === '3x2';
}
