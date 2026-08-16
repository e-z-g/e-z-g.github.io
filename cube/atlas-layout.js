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
// A naming caveat, worth knowing before you trust either label set
//
// The viewer's *separate-image* path (getCubemapUrls) hands its six URLs to the
// material slots in the order [left, right, top, bottom, back, front], i.e. it
// considers slot 4 to be "back" and slot 5 "front". The *atlas* path assigns
// slot 4 to the cell this module calls "front" and slot 5 to "back" — the
// opposite, and likewise for left/right.
//
// The two paths never meet, so each is self-consistent, but a set of six files
// stitched into an atlas comes out rotated 180 degrees in yaw compared with the
// same files loaded through the separate-image path. That is a different
// starting heading, not a mirrored or broken cube. The atlas convention below
// is the one both this module and sampleAtlas() follow; it is left as-is so
// existing atlases keep working.
// ============================================================================

export const FACES = ['left', 'front', 'right', 'back', 'top', 'bottom'];

export const FACE_LABELS = {
  left:  'Left (−X)',  front: 'Front (+Z)',
  right: 'Right (+X)', back:  'Back (−Z)',
  top:   'Top (+Y)',   bottom:'Bottom (−Y)'
};

// Face name -> viewer material index, for the atlas paths.
export const FACE_INDEX = { right: 0, left: 1, top: 2, bottom: 3, front: 4, back: 5 };
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
      { face: 'left',   rot:   0, note: 'Left'  },
      { face: 'front',  rot:   0, note: 'Front' },
      { face: 'right',  rot:   0, note: 'Right' },
      { face: 'back',   rot:   0, note: 'Back'  },
      { face: 'left',   rot:   0, note: 'L dup' },
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
      { face: 'left',  rot: 0, note: 'Left'  },
      { face: 'front', rot: 0, note: 'Front' },
      { face: 'right', rot: 0, note: 'Right' },
      { face: 'back',  rot: 0, note: 'Back'   },
      { face: 'top',   rot: 0, note: 'Top'    },
      { face: 'bottom',rot: 0, note: 'Bottom' },
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

// Face-local UV in [0,1] -> unnormalised direction. Inverse of gnomonicUV.
export function faceUvToDir(faceIndex, u, v) {
  const a = u * 2 - 1, b = v * 2 - 1;
  switch (faceIndex) {
    case 0: return [-1,  b, -a];
    case 1: return [ 1,  b,  a];
    case 2: return [ a,  1, -b];
    case 3: return [ a, -1,  b];
    case 4: return [ a,  b,  1];
    default:return [-a,  b, -1];
  }
}

// Direction -> { faceIndex, u, v }. Forward gnomonic projection.
export function dirToFaceUv(x, y, z) {
  const ax = Math.abs(x), ay = Math.abs(y), az = Math.abs(z);
  let faceIndex, a, b;
  if (ax >= ay && ax >= az) {
    if (x < 0) { faceIndex = 0; a = -z / ax; b =  y / ax; }
    else       { faceIndex = 1; a =  z / ax; b =  y / ax; }
  } else if (ay >= az) {
    if (y > 0) { faceIndex = 2; a =  x / ay; b = -z / ay; }
    else       { faceIndex = 3; a =  x / ay; b =  z / ay; }
  } else {
    if (z > 0) { faceIndex = 4; a =  x / az; b =  y / az; }
    else       { faceIndex = 5; a = -x / az; b =  y / az; }
  }
  return { faceIndex, u: a * 0.5 + 0.5, v: b * 0.5 + 0.5 };
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
    vec2 inset = mix(vec2(uGutterFrac), vec2(1.0 - uGutterFrac), local);
    if (face == 1) return texture2D(tex, getGrid(0.0, 0.0, inset));
    if (face == 4) return texture2D(tex, getGrid(1.0, 0.0, inset));
    if (face == 0) return texture2D(tex, getGrid(2.0, 0.0, inset));
    if (face == 5) return texture2D(tex, getGrid(0.0, 1.0, inset));
    if (face == 2) return texture2D(tex, getGrid(1.0, 1.0, inset));
    return texture2D(tex, getGrid(2.0, 1.0, inset));
  }
`;

export function sampleAtlasGlsl(layoutId) {
  return GLSL_HELPERS + (layoutId === '3x2' ? GLSL_3X2 : GLSL_5X3);
}

// True when the layout's shader declares a uGutterFrac uniform.
export function layoutUsesGutter(layoutId) {
  return layoutId === '3x2';
}
