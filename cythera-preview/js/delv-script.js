/* delv-script.js -- the Delver VM: word decoding, the opcode table, the symbol
 * tables, and the disassembler that turns a script resource into text.
 *
 * Text, not markup. dvmRender() returns an array of lines and dvmDiscover()
 * returns a description of what is in a resource; the page turns those into
 * HTML in buildScriptView(). The `<array>` and `<table>` that appear in the
 * output here are placeholders in a plain-text disassembly, not tags.
 *
 * Almost everything in this file is delvmod's work, transcribed. The 59-opcode
 * table with its operand counts, the eight symbol tables, the mnemonics and
 * the word encoding in dvmWord() all come from delv/ddasm.py, and a
 * disassembly produced here is meant to read the same way as one produced
 * there. utilities/delv_crosscheck.mjs re-parses all of it out of the Python on
 * every run, because a copied table drifts silently -- nothing in a browser
 * complains that a syscall is labelled with the wrong name.
 *
 * See delv-archive.js for why these are classic scripts and why the three
 * delv-* files are organisation rather than a library. LOAD ORDER: after
 * delv-archive.js; before the page.
 */

// Raw 4-byte words of an array, as stored. dvmArrayContents() formats them for
// the disassembly; a stat panel needs the numbers themselves.
function dvmArrayWords(b, off) {
  if (off + 2 > b.length) return null;
  const size = u16be(b, off) & 0x0FFF;
  if (size < 1 || size > 64 || off + 2 + size * 4 > b.length) return null;
  const out = [];
  for (let i = 0; i < size; i++) {
    const o = off + 2 + i * 4;
    out.push(u32be(b, o));
  }
  return out;
}

function itemStringAt(b, off) {
  let end = off;
  while (end < b.length && b[end] !== 0 && end - off < 160) end++;
  if (end - off < 4) return null;
  for (let i = off; i < end; i++) if (b[i] < 0x20 && b[i] !== 9) return null;
  const s = decodeMacRoman(b.subarray(off, end)).trim();
  return /[A-Za-z]{3}/.test(s) ? s : null;
}

// ===================== Delver VM disassembler =====================
// Ported from delvmod's DDASM. Script resources are DVM containers: the first
// byte selects the type (0x81 function, 0x9x array, 0xAx table, otherwise a
// class). A class is a u16 offset to a field table of {u32 value, u16 key};
// entries with the high bit set and a matching resource id point at members.
//
// The subtlety that breaks a naive linear walk: opcode 0x40 ("end") closes an
// expression sub-stream, and when it closes an if / if_not / switch it also
// carries a u16 branch target. Everywhere else it has no operand. Without an
// expectation stack the decoder desyncs by two bytes after every conditional.
// The mnemonics are delvmod's, from the OpTable in delv/ddasm.py, so that a
// disassembly here and one from delvmod read the same way -- `bitwise_and`
// rather than `bitand`, `left_shift` rather than `shl`, `string` rather than
// `pushc`. utilities/delv_crosscheck.mjs compares the whole table on every run
// and lists any deliberate divergence (there is one: `local`, which is more
// readable than delvmod's `loc` and is not a name anyone greps for).
// Each entry is [mnemonic, operand size, operand-expression count]; the last
// is delvmod's `expect`, the number of nested expressions the opcode consumes.
const DVM_OPS = {
  0x41:['byte',1,0], 0x42:['short',2,0], 0x43:['word',4,0], 0x44:['string','c',0],
  0x45:['data','D',0], 0x46:['index',0,0], 0x47:['load_near_word',2,0],
  0x48:['global',1,0], 0x49:['load_far_word',4,0],
  0x4A:['add',0,0], 0x4B:['sub',0,0], 0x4C:['mul',0,0], 0x4D:['div',0,0],
  0x4E:['mod',0,0], 0x4F:['lt',0,0], 0x50:['le',0,0], 0x51:['gt',0,0],
  0x52:['ge',0,0], 0x53:['ne',0,0], 0x54:['eq',0,0], 0x55:['neg',0,0],
  0x56:['bitwise_and',0,0], 0x57:['bitwise_or',0,0], 0x58:['bitwise_xor',0,0], 0x59:['bitwise_not',0,0],
  0x5A:['left_shift',0,0], 0x5B:['right_shift',0,0], 0x5C:['and',0,0], 0x5D:['or',0,0],
  0x5E:['not',0,0], 0x5F:['len',0,0], 0x60:['has_member',1,0], 0x61:['class_member',2,0],
  0x62:['get_field',1,0], 0x63:['cast',1,0], 0x64:['is_type',1,0],
  0x81:['subroutine',2,0], 0x82:['set_local',1,1], 0x83:['write_near_word',2,1],
  0x84:['set_index',0,3], 0x85:['write_far_word',4,1], 0x86:['set_field',1,2],
  0x87:['set_global',1,1], 0x88:['branch',2,0], 0x89:['switch',0,1],
  0x8A:['print',0,1], 0x8B:['return',0,1], 0x8C:['if',0,1], 0x8D:['if_not',0,1],
  0x8E:['exit',0,0], 0x8F:['conversation_prompt','c',0],
  0x90:['conversation_response','C',0], 0x92:['ai_state',1,1], 0x93:['gui_close',0,1],
  0x9B:['gui',1,1], 0x9C:['call_index',2,2], 0x9D:['method',1,1],
  0x9E:['call_subroutine',2,1], 0x9F:['call_resource',2,1]
};
const DVM_TARGETED = new Set([0x8C, 0x8D, 0x89]);

// delvmod's dispatch: 0x00-0x2F local, 0x30-0x3F arg, 0x40 closes an
// expectation, >=0xA0 is a system call whose number IS the opcode byte (no
// operand, one expression list), otherwise the opcode table.
// Word encoding, from the wiki's Word page. A 4-byte value is not just an
// integer: the top nibble selects a type, and drefs are 0x80000000|(resid<<16)|offset.
/* Which resource is being disassembled, so a reference into it can be shown as
 * `here:` rather than repeating its own id on every line. delvmod calls this
 * `context_resource`; it is set for the duration of a render. */
let dvmContextResid = null;

/* Name a resource id the way the disassembly should read it. */
function dvmResourceName(rid) {
  const sym = (typeof resourceSymbol === 'function' && resourceSymbol(rid)) ||
              (DVM_SYM.resource && DVM_SYM.resource[String(rid)]);
  const hex = '0x' + rid.toString(16).toUpperCase().padStart(4, '0');
  return sym ? sym + ' (' + hex + ')' : hex;
}

/* A 4-byte value is not an integer with a tag on it: the top nibble selects a
 * type, and each type reads the remaining bits differently. The cases below
 * follow delvmod's word2str (delv/ddasm.py), which is the most complete
 * reading of this anyone has written down. Three of them were missing here:
 *
 *   - Negative numbers. The range is 28 bits, sign-extended, so 0x0FFFFFF1 is
 *     -15, not 268,435,441. Every negative constant in every script was being
 *     shown as a nine-digit positive one; 34 lines of the archive's readable
 *     disassembly were affected. `SetLandscapeImage -15` is a line you can
 *     read, and `SetLandscapeImage 268435441` is not.
 *   - Object references other than characters. Bits 16-23 are the class, so
 *     0x40200005 is zone 5, not an unexplained hex constant. Only the
 *     character case (class 0x40) was handled.
 *   - 0x5000FFFE, which is `empty` -- the empty value, distinct from `none`.
 */
function dvmWord(v) {
  v = v >>> 0;
  // Signed 28-bit integer.
  if (v <= 0x07FFFFFF) return String(v);
  if (v <= 0x0FFFFFFF) return String(v - 0x10000000);
  // 0x1xxxxxxx: a reference to one of the enclosing function's locals.
  //
  // delvmod treats 0x10000000-0x2FFFFFFF as unidentified and the wiki's Word
  // page reads the 0x1 nibble as a variable reference, so this was a guess
  // where the rest of this function is evidence. It has since been checked
  // against the whole archive, and the wiki is right:
  //
  //   * all 456 of these references have an index inside their own function's
  //     declared local count -- not one lands outside,
  //   * 441 of the 456 (97%) name a local that the same function also reads
  //     directly with a `local` opcode, which is what a reference to a
  //     variable should look like,
  //   * the encoded values run 1..13 and 0 never appears, so the encoding is
  //     1-based and the -1 below is right.
  //
  // Random 28-bit values would not land in a 13-wide window 456 times.
  // utilities/delv_crosscheck.mjs re-runs the first two of those every time.
  if ((v & 0xF0000000) >>> 0 === 0x10000000) return '&Var' + ((v & 0x0FFFFFFF) - 1);
  if (v < 0x30000000) return '0x' + v.toString(16).toUpperCase();
  // Resource with an index: `Resources.PickLock[2]`.
  if (v < 0x40000000) return dvmResourceName(v & 0xFFFF) + '[' + ((v >>> 16) & 0x0FFF) + ']';
  // Object reference: class in bits 16-23, instance in the low word.
  if (v < 0x50000000) {
    const cls = (v >> 16) & 0xFF, which = v & 0xFFFF;
    const clsName = DVM_SYM.objtype && DVM_SYM.objtype[String(cls)];
    if (cls === 0x40) {
      const n = DVM_SYM.character && DVM_SYM.character[String(which)];
      return 'Character.' + (n || ('0x' + which.toString(16).toUpperCase()));
    }
    const w = '0x' + which.toString(16).toUpperCase().padStart(4, '0');
    return w + '@' + (clsName ? 'Type.' + clsName : '0x' + cls.toString(16).toUpperCase());
  }
  if (v === 0x50000000) return 'False';
  if (v === 0x50000001) return 'True';
  if (v === 0x5000FFFF) return 'None';
  if (v === 0x5000FFFE) return 'Empty';
  if (v < 0x80000000) return '0x' + v.toString(16).toUpperCase();
  // dref: a resource id and a byte offset inside it.
  {
    const rid = (v & 0x7FFF0000) >>> 16, off = v & 0xFFFF;
    const where = '0x' + off.toString(16).padStart(4, '0').toUpperCase();
    if (dvmContextResid !== null && rid === dvmContextResid) return 'here:' + where;
    return dvmResourceName(rid) + ':' + where;
  }
}

// Classes by resource range, from the wiki's Object page.
function dvmClassName(resid) {
  const hi = resid >> 8;
  if (hi === 0x10 || hi === 0x11 || hi === 0x12 || hi === 0x13) return 'Item';
  if (hi === 0x14) return 'Zone';
  if (hi === 0x15) return 'SubZone';
  if (hi === 0x18) return 'Character';
  if (hi === 0x19) return 'MonsterDeaths';
  if (hi === 0x1A) return 'Skill';
  if (hi === 0x1B || hi === 0x1C) return 'Room';
  if (hi === 0x1E) return 'Unknown1E';
  if (hi === 0x30) return 'DefaultMethods';
  return null;
}

// Scalars are wrapped in single-element arrays because a table value must be a
// dref (Table page), so decoding array contents is what actually reveals
// things like an item's weight.
function dvmArrayContents(seg) {
  if (seg.length < 2) return null;
  const size = u16be(seg, 0) & 0x0FFF;
  if (size > 64 || 2 + size*4 > seg.length) return null;
  const vals = [];
  for (let i = 0; i < size; i++) {
    const o = 2 + i*4;
    vals.push(dvmWord(u32be(seg, o)));
  }
  return vals;
}

// Symbol tables lifted from delvmod's symbolics module: 96 system calls, 46
// object methods, 38 struct fields, 16 globals, plus GUI, object-type,
// resource and character names. Without these the disassembly is numerically
// correct but unreadable.
//
// CAVEAT on the `field` names below: they follow the wiki's Delver Script
// Structs page, which lists field 1 as `x` and field 3 as `aspect`. The Door
// Script contradicts that -- it compares field 3 against 0/1/2/4 with the
// messages "It is locked" and "It is magically locked", which is a lock
// state, and it adjusts field 1 by one when the door opens, which behaves
// like a frame index. The prop records agree with the Door Script: doors are
// placed at aspects 5, 7, 9 and 11, values field 3 never takes. So expect
// `set_field aspect` in a door disassembly to be mislabelled; the struct
// table has not been rewritten here because nothing else contradicts it.
const DVM_SYM = {"syscall":{"160":"RangeIterator","161":"ArrayIterator","162":"GameOver","163":"UseTime","164":"TalkParticipant","165":"UnseenA5","166":"Delay","167":"Delete","168":"Create","169":"GetMapTile","170":"UnseenAA","171":"TakeItem","172":"Random","173":"New","174":"WhoHasItem","175":"UnseenAF","176":"UnseenB0","177":"RemoveItem","178":"UnseenB2","179":"UnseenB3","180":"ModalNumberInput","181":"UnseenB5","182":"UnseenB6","183":"WeightCapacity","184":"GetWeight","185":"JoinParty","186":"LeaveParty","187":"ModalPartySelector","188":"IsInParty","189":"PassTime","190":"UpdateLighting","191":"ChangeZone","192":"ShowMenu","193":"SetFlag","194":"ClearFlag","195":"StatusEffect","196":"TestFlag","197":"EmitSignal","198":"UnseenC6","199":"PropListIterator","200":"ContainerIterator","201":"RecursiveContainerIterator","202":"PartyIterator","203":"LocationIterator","204":"EquipmentIterator","205":"UnseenCD","206":"EnemyIterator","207":"EffectIterator","208":"MonsterIterator","209":"NearbyIterator","210":"PlayNote","211":"PlaySound","212":"UnknownD4","213":"UnseenD5","214":"PlayMusic","215":"PlayAmbientSound","216":"SetAmbientLighting","217":"SetLandscapeImage","218":"SetTitle","219":"HasWindow","220":"GetState","221":"SetState","222":"GetStateFlag","223":"SetStateFlag","224":"UnknownE0","225":"MagicAuraEffect","226":"ShootEffect","227":"FlashTile","228":"HitWithTile","229":"GetNextProp","230":"RefreshView","231":"SpecialView","232":"OpenConversation","233":"FinishConversation","234":"BeginCutscene","235":"EndCutscene","236":"BeginSlideshow","237":"EndSlideshow","238":"Slideshow","239":"UnseenEF","240":"AddTask","241":"FinishTasks","242":"AddQuest","243":"CompleteQuest","244":"AddConversationKeyword","245":"GetSkill","246":"SetViewPosition","247":"HasSightLine","248":"CDPlayerControl","249":"UnseenF9","250":"GetProp","251":"UnseenFB","252":"SetAutomapping","253":"SetBackgroundColor","254":"UnseenFE","255":"UnseenFF"},"field":{"0":"flags","1":"x","2":"y","3":"aspect","4":"obj_type","5":"aspect_and_proptype","6":"data1","7":"data2","8":"data3","9":"quantity","10":"tile","11":"container","12":"erode_effect","13":"rotate","17":"has_storage","18":"storage","19":"bit_flags","20":"status_flags","21":"behavior","22":"behavior2","23":"body","24":"reflex","25":"mind","26":"exp","27":"level","28":"health","29":"full_health","30":"magic","31":"full_magic","32":"dispatch_thing","33":"training","34":"target","35":"timing","38":"talk_balloon","40":"nutrition","41":"room_occupied","50":"monster_flags","53":"alignment"},"method":{"2":"Look","4":"HasSkill","7":"LookAt","8":"Examine","9":"Use","10":"UseOn","11":"UseAt","12":"Talk","13":"Wear","14":"UnWear","15":"Take","16":"PutInside","17":"Relinquish","20":"Enter","21":"GetMessage","23":"IsContainer","26":"Learn","29":"OnDeath","31":"StepOn","32":"EveryTurn","34":"Chair","35":"Mirror","36":"Weight","38":"Equipment","39":"ClassFlags","40":"Stacking","42":"MeleeWeapon","43":"ThrownWeapon","44":"ArmorValue","45":"Ammunition","46":"RangedWeapon","47":"Shield","48":"AlchemicalReagent","50":"LightSource","51":"AskedAbout","52":"Lockable","53":"UseLock","54":"AIInformation","57":"Dug","58":"Portal","59":"SoundEffects","60":"MoneyValue","64":"ResistDamage","65":"TakeDamage","68":"SpellsKnown","69":"NegotiationPoints"},"gui":{"4":"Create","6":"Text","8":"Button","15":"Instrument","17":"Spinner","20":"TextBox"},"global":{"0":"CurrentHour","1":"CurrentTime","2":"PlayerCharacterName","5":"PlayerCharacter","6":"CharactersInParty","7":"CharactersInParty2","9":"CurrentCharacter","10":"ConversationResponse","12":"Karma","13":"Registered","14":"LanguagesKnown","15":"GameDay","16":"CurrentZone","17":"DifficultyLevel","18":"CurrentRoom","19":"IsPlayerTurn"},"objtype":{"0":"Prop","32":"Zone","64":"Character","72":"Monster","80":"Skill","88":"Room"},"resource":{"2070":"GiveDirections","3206":"BlacksmithTasker","3332":"CountMoneyInParty","3651":"PickLock","3718":"AdjCharLevel","3723":"GainExp","3745":"CastSpell","3766":"AskAbout","3840":"SetCharacterFlag"},"character":{"0":"NoCharacter","1":"Hero","2":"Alaric","3":"Magpie","4":"Hadrian","5":"Emesa","6":"Hector","7":"LKH_Guard","8":"Cademia_Guard","9":"Ruins_Guard","10":"Myus","11":"Naxos","12":"Darius","13":"Pelagon","14":"Deiphobus","15":"Kosha_Guard","16":"Atreus","17":"Ennomus","18":"Ariethous","19":"Laodice","20":"Thuria","21":"Malis","22":"Cybele","23":"Amphidamas","24":"Eurybates","25":"Rhesus","26":"Lycurgus","27":"Erechtheus","28":"Thamyris","29":"Atymnius","30":"Milcom","31":"Sardis","32":"Ake","33":"Neoptolemus","34":"Meleager","35":"Hebe","36":"Antenor","37":"Alastor","38":"Aeneas","39":"Eioneus","40":"Parium","41":"Crito","42":"Apis","45":"Dares","46":"Diomede","48":"Thetis","49":"Bias","50":"Philinus","51":"Opheltius","52":"Ascalon","53":"Ariadne","54":"Odemia_Guard","55":"Tlepolemus","56":"Eteocles","57":"Laomedon","58":"Ilus","59":"Autonous","60":"Propontis","61":"Mantinea","62":"Halos","63":"Catamarca_Guard","64":"Oeneus","65":"Periphas","66":"Theano","67":"Hypsenor","68":"Thoas","69":"Dymas","70":"Sacas","71":"Metopes","72":"Berossus","73":"Itanos","74":"Timon","75":"Prusa","76":"Bryaxis","77":"Anisa","78":"Pheres","79":"Charax","80":"Lindus","81":"Selinus","82":"Palaestra","83":"Tros","84":"Pnyx_Guard","85":"Alcestris","86":"Asius","87":"Paris","88":"Helen","89":"Niobe","90":"Larisa","91":"Joppa","92":"Eudoxus","93":"Eumelus","94":"Antiphus","95":"Polydamas","96":"Peirithous","97":"Aethon","98":"Dryas","100":"Gate_Guard","101":"Thersites","102":"Glaucus","103":"Borus","104":"Briseis","105":"Pelops","106":"Alcmena","107":"Asteropaeus","108":"Stentor","109":"Demodocus","110":"Thrasymedes","111":"Protesilaus","112":"Menelaus","113":"Lycaon","114":"Peleus","115":"Peisander","116":"Danae","117":"Semele","118":"Alcyone","119":"Clytemnestra","120":"Sabinate","121":"Jhiaxus","122":"Unhayt","123":"Seqedher","124":"Uset","125":"Ignae","126":"Omen","127":"UrSylph","189":"Wishing_Fountain","190":"Degree_Hall_Door"}};
function loadResourceSymbols() {
  if (window.RESOURCE_SYMBOLS) return window.RESOURCE_SYMBOLS;
  const names = {};
  try {
    const raw = getResourceBytes(0x0101);
    if (raw) {
      const d = smartDecrypt(raw, 0x0101).data;
      const n = u16be(d, 0) & 0x0FFF;
      let p = 2;
      for (let i = 0; i < n && p + 6 <= d.length; i++) {
        const v = u32be(d, p);
        const k = u16be(d, p+4);
        p += 6;
        if (!(v & 0x80000000)) continue;
        if (((v & 0x7FFF0000) >>> 16) !== 0x0101) continue;
        let off = v & 0xFFFF, str = '';
        while (off < d.length && d[off] >= 32 && d[off] < 127 && str.length < 48) str += String.fromCharCode(d[off++]);
        if (str) names[k] = str;
      }
    }
  } catch (e) {}
  return (window.RESOURCE_SYMBOLS = names);
}
function resourceSymbol(resid) { return loadResourceSymbols()[resid] || null; }

function dvmSym(table, code) {
  const t = DVM_SYM[table];
  const n = t && t[String(code)];
  return n ? n + ' (0x' + code.toString(16).toUpperCase() + ')' : '0x' + code.toString(16).padStart(2,'0').toUpperCase();
}

function dvmOpEntry(op) {
  const e = DVM_OPS[op];
  if (e) return e;
  if (op >= 0xA0) {
    const n = DVM_SYM.syscall && DVM_SYM.syscall[String(op)];
    return ['sys ' + (n || ('0x' + op.toString(16).toUpperCase())), 0, 1];
  }
  return null;
}

// The wiki's "Strings Problem" page documents an unsolved case: a body like
//   81 01 00  "You can't dig here!" 0A  8B 41 00 40
// where a raw string sits in the instruction stream with no 0x44 marker and
// ends at any non-printing byte. The page offers THREE possibilities without
// preferring any of them: that the leading character is a special case, that
// the VM sees an empty stack and infers that what follows cannot be an
// opcode, or that string-to-output is simply the default mode. Only the
// second is something this decoder can act on, and it happens to line up with
// the drain boundary already tracked here -- so that is the one implemented,
// not because the wiki endorses it. At a drain (or at a body's very start) a
// run of printable bytes ending in a control byte is read as an implicit
// string, and decoding resumes afterwards instead of giving up.
function dvmImplicitString(b, p) {
  let q = p;
  while (q < b.length && b[q] >= 0x20 && b[q] < 0x7F) q++;
  if (q - p < 3) return null;
  if (q >= b.length) return { text: null, next: q };
  const t = b[q];
  // The Strings Problem page: "many things besides 0x00 can terminate a
  // string, including at least 8x series opcodes - perhaps any nonprinting
  // character." So a run may end on a control byte OR on a statement opcode
  // (0x811 ends "mine,iron" on 0x00; 0x1148 ends "The " on 0x9E).
  if (t >= 0x20 && t < 0x80) return null;
  let str = '';
  for (let i = p; i < q; i++) str += String.fromCharCode(b[i]);
  // the terminator itself belongs to the string when it is whitespace
  const next = (t === 0x0A || t === 0x0D || t === 0x00 || t === 0x09) ? q + 1 : q;
  return { text: str, next };
}

function dvmDisassemble(b, start) {
  const out = []; let p = start || 0, bad = 0; const stack = [];
  let opened = false;
  let lastDrain = null;
  {
    const imp = dvmImplicitString(b, p);
    if (imp && imp.text !== null) { out.push([p, 0, 'string(implicit)', JSON.stringify(imp.text)]); p = imp.next; }
  }
  const hex = (o,n) => { let s=''; for (let i=0;i<n;i++) s += b[o+i].toString(16).padStart(2,'0').toUpperCase(); return s; };
  while (p < b.length) {
    const op = b[p], at = p; p++;
    if (op < 0x30) { out.push([at, 0, 'local', 'Var' + op.toString(16).padStart(2,'0').toUpperCase()]); continue; }
    if (op < 0x40) { out.push([at, 0, 'arg', 'Arg' + (op - 0x30).toString(16).padStart(2,'0').toUpperCase()]); continue; }
    if (op === 0x40) {
      const owner = stack.pop();
      if (DVM_TARGETED.has(owner) && p + 2 <= b.length) {
        out.push([at, -1, 'then', '-> 0x' + u16be(b, p).toString(16).padStart(4,'0').toUpperCase()]); p += 2;
      } else out.push([at, -1, 'end', '']);
      // delvmod drops out of code mode whenever the expectation stack drains,
      // and can re-enter it, so a drain is NOT the end of the function -- it is
      // a safe place to cut if what follows turns out not to be code. Record
      // it and keep decoding.
      if (!stack.length) {
        lastDrain = [out.length, p];
        const imp = dvmImplicitString(b, p);
        if (imp && imp.text !== null) {
          out.push([p, 0, 'string(implicit)', JSON.stringify(imp.text)]);
          p = imp.next;
          lastDrain = [out.length, p];
        }
      }
      continue;
    }
    const e = dvmOpEntry(op);
    if (!e) {
      // Garbage after a complete statement means code ended there and the rest
      // is data; rewind to that boundary rather than report a desync.
      if (lastDrain) return { ops: out.slice(0, lastDrain[0]), bad: 0 };
      bad++; out.push([at, 0, '??', '0x' + op.toString(16).padStart(2,'0')]); continue;
    }
    const mn = e[0], spec = e[1], expect = e[2];
    let arg = '';
    if (spec === 'c' || spec === 'C') {
      let z = p;
      while (z < b.length && b[z] !== 0) z++;
      const s = decodeMacRoman(b.subarray(p, z));
      p = z + 1;
      arg = JSON.stringify(s);
      if (spec === 'C') { arg += ' -> 0x' + (p + 2 <= b.length ? u16be(b, p) : 0).toString(16).padStart(4,'0').toUpperCase(); p += 2; }
    } else if (spec === 'D') {
      const sz = p + 2 <= b.length ? u16be(b, p) : 0; p += 2 + sz; arg = '<' + sz + ' bytes>';
    } else if (spec === 1 && (mn === 'get_field' || mn === 'set_field')) {
      arg = dvmSym('field', b[p]); p += 1;
    } else if (spec === 1 && (mn === 'method' || mn === 'has_member')) {
      arg = dvmSym('method', b[p]); p += 1;
    } else if (spec === 1 && (mn === 'global' || mn === 'set_global')) {
      arg = dvmSym('global', b[p]); p += 1;
    } else if (spec === 1 && mn === 'gui') {
      arg = dvmSym('gui', b[p]); p += 1;
    } else if (spec === 1 && (mn === 'cast' || mn === 'is_type')) {
      arg = dvmSym('objtype', b[p]); p += 1;
    } else if (spec === 2 && mn === 'call_resource') {
      const rid = u16be(b, p); p += 2;
      const nm = resourceSymbol(rid);
      arg = nm ? nm + ' (0x' + rid.toString(16).toUpperCase() + ')' : dvmSym('resource', rid);
    } else if (spec === 4 && mn === 'word') {
      arg = dvmWord(u32be(b, p));
      p += 4;
    } else if (spec) { arg = '0x' + hex(p, spec); p += spec; }
    out.push([at, expect ? 1 : 0, mn, arg]);
    for (let k = 0; k < expect; k++) { stack.push(op); opened = true; }
    // An empty stack is the VM's own cue that what follows need not be code
    // (Strings Problem page), so probe for an implicit string here too.
    if (!expect && !stack.length) {
      const imp2 = dvmImplicitString(b, p);
      if (imp2 && imp2.text !== null) {
        out.push([p, 0, 'string(implicit)', JSON.stringify(imp2.text)]);
        p = imp2.next;
        lastDrain = [out.length, p];
      }
    }
  }
  return { ops: out, bad };
}

// Objects are discovered by following references rather than assuming the
// class table lists them all. An extent runs from an object's offset to the
// next discovered offset, so a function stops where real data begins instead
// of marching into it. This is what took coverage from 67% to 80%.
// Does this byte stream parse as a Delver VM container for `resid`? A valid
// function has sane arg/local counts; a valid class points at a field table
// whose entries include at least one dref back into this same resource.
// Subindex 3 does not use the dispatch-table container at all. Each resource
// is a Pascal-style name followed by raw bytecode: 0x0410 is 0x0E "Attack
// Nearest" and then the script body. All fourteen are stored in the clear.
// They are the AI combat routines -- Attack Nearest / Weakest / Strongest,
// Defend, Beserk (sic), Missile Script, Healer -- in two near-identical banks
// at 0x041x and 0x043x. Nothing in the archive references them by id, so they
// are almost certainly selected by name or by index from the application.
function dvmNamedScript(b) {
  if (!b || b.length < 6) return null;
  const n = b[0];
  if (n < 3 || n > 63 || n + 2 >= b.length) return null;
  for (let i = 1; i <= n; i++) if (b[i] < 0x20 || b[i] > 0x7E) return null;
  const name = decodeMacRoman(b.subarray(1, n + 1));
  if (!/[A-Za-z]/.test(name)) return null;
  return { name, bodyOffset: n + 1 };
}

function dvmPlausibleContainer(b, resid) {
  if (!b || b.length < 4) return false;
  const v = b[0];
  if (v === 0x81) return b[1] < 0x10 && b[2] < 0x30;
  if ((v & 0xF0) === 0x90 || (v & 0xF0) === 0xA0) return true;
  const toff = u16be(b, 0);
  if (toff < 2 || toff + 2 > b.length) return false;
  const count = u16be(b, toff) & 0x0FFF;
  if (count === 0 || toff + 2 + count * 6 > b.length + 6) return false;
  let hits = 0;
  for (let i = 0, p = toff + 2; i < count && p + 6 <= b.length; i++, p += 6) {
    const value = u32be(b, p);
    if (!(value & 0x80000000)) continue;
    if (((value & 0x7FFF0000) >>> 16) !== resid) continue;
    if ((value & 0xFFFF) < b.length) hits++;
  }
  return hits > 0;
}

function dvmDiscover(b, resid) {
  const n = b.length;
  if (!n) return { tableOffset: null, kinds: {} };
  const kindAt = off => {
    if (off >= n) return 'oob';
    const v = b[off];
    // delvmod's DFunction asserts arg_count < 0x10 and local_count < 0x30. A
    // leading 0x81 that violates those is data that merely starts with 0x81
    // (e.g. 0x1050 claims 83 locals), so do not decode it as code.
    if (v === 0x81 && b[off+1] < 0x10 && b[off+2] < 0x30) return 'function';
    if ((v & 0xF0) === 0x90) return 'array';
    if ((v & 0xF0) === 0xA0) return 'table';
    return 'data';
  };
  const head = b[0];
  let tableOffset, roots;
  // The offset-0 fast path was bypassing the arg/local sanity check, so
  // 0x1050 (14 args, 83 locals) and 0x1914 (12 args, 185 locals) were being
  // decoded as code when they are not functions at all.
  if (head === 0x81) {
    const ok = b[1] < 0x10 && b[2] < 0x30;
    return { tableOffset: n, kinds: { 0: ok ? 'function' : 'data' } };
  }
  if ((head & 0xF0) === 0x90 || (head & 0xF0) === 0xA0) { tableOffset = n; roots = [0]; }
  else {
    tableOffset = u16be(b, 0);
    if (tableOffset + 2 > n) return { tableOffset: null, kinds: {} };
    roots = [tableOffset];
  }
  const kinds = {}, seen = new Set(), work = roots.slice();
  while (work.length) {
    const off = work.pop();
    if (seen.has(off) || off >= n) continue;
    seen.add(off);
    const k = kindAt(off); kinds[off] = k;
    if (k === 'array' || k === 'table' || off === tableOffset) {
      const size = u16be(b, off) & 0x0FFF;
      const stride = (k === 'table' || off === tableOffset) ? 6 : 4;
      let p = off + 2;
      for (let i = 0; i < size && p + stride <= n; i++) {
        const value = u32be(b, p); p += stride;
        if (!(value & 0x80000000)) continue;
        if (((value & 0x7FFF0000) >>> 16) !== resid) continue;
        const t = value & 0xFFFF;
        if (t < n && !seen.has(t)) work.push(t);
      }
    }
  }
  return { tableOffset, kinds };
}

function dvmExtents(b, resid) {
  const { tableOffset, kinds } = dvmDiscover(b, resid);
  if (tableOffset === null) return [];
  const offs = Object.keys(kinds).map(Number).filter(o => o !== tableOffset).sort((x, y) => x - y);
  return offs.map((o, i) => {
    let nxt = i + 1 < offs.length ? offs[i+1] : tableOffset;
    if (nxt <= o) nxt = tableOffset;
    return [o, Math.min(nxt, b.length), kinds[o]];
  });
}

// A code body often hits a NUL early and reads as punctuation, so demand real
// prose: some length, a space, and almost everything printable.
// Short NUL-terminated identifiers ("Attack", "ToggleLock", "gCharNames")
// are strings too. The prose test demands a space and some length, which is
// right for dialogue but wrong for symbol names -- they were the bulk of what
// showed as raw byte counts.
function dvmIsIdentifier(seg) {
  if (seg.length < 2 || seg.length > 64) return false;
  if (seg[seg.length - 1] !== 0) return false;
  for (let i = 0; i < seg.length - 1; i++) {
    const c = seg[i];
    if (c < 32 || c >= 127) return false;
  }
  return true;
}

function dvmIsProse(seg) {
  if (seg.length < 8) return false;
  let hasSpace = false, good = 0;
  for (const c of seg) {
    if (c === 0x20) hasSpace = true;
    if ((c >= 32 && c < 127) || c >= 0x80 || c === 9 || c === 10 || c === 13) good++;
  }
  return hasSpace && good / seg.length > 0.95;
}

function dvmLooksLikeText(seg) {
  if (seg.length < 4) return false;
  let ascii = 0, ctrl = 0;
  for (const c of seg) {
    if ((c >= 32 && c < 127) || c === 9 || c === 10 || c === 13) ascii++;
    else if (c < 0x20) ctrl++;
  }
  return (ascii / seg.length > 0.9) || (ctrl / seg.length < 0.02);
}

function dvmRender(b, resid) {
  // So a dref back into this same resource reads as `here:0x0031`.
  dvmContextResid = (typeof resid === 'number') ? resid : null;
  const objs = dvmExtents(b, resid);
  const lines = [];
  let clean = 0, failed = 0;
  const hex4 = v => v.toString(16).padStart(4,'0').toUpperCase();
  const str = seg => decodeMacRoman(seg.filter(c => c));
  for (const [st, en, kind] of objs) {
    const seg = b.subarray(st, Math.min(en, b.length));
    if (!seg.length) continue;
    const name = 'obj_' + hex4(st);
    if (kind === 'function') {
      const body = seg.subarray(3);
      let z = -1;
      for (let i = 0; i < body.length; i++) if (body[i] === 0) { z = i; break; }
      const head = z > 0 ? body.subarray(0, z) : body;
      if (dvmIsProse(head)) { lines.push('', name + ' = ' + JSON.stringify(str(head))); clean++; continue; }
      const r = dvmDisassemble(seg, 3);
      lines.push('', 'function ' + name + '(' + seg[1] + ' args, ' + seg[2] + ' locals) {');
      let ind = 1;
      for (const op of r.ops) {
        const at = op[0], delta = op[1], mn = op[2], arg = op[3];
        if (delta < 0 && ind > 1) ind--;
        lines.push('  ' + hex4(at) + '  ' + '    '.repeat(ind) + mn + (arg ? ' ' + arg : ''));
        if (delta > 0) ind++;
      }
      lines.push('}');
      if (r.bad) { lines.push('// ^ decoder desynced (' + r.bad + ' unrecognised bytes) - unreliable'); failed++; }
      else clean++;
    } else if (kind === 'array') {
      const v = dvmArrayContents(seg);
      lines.push('', name + ' = ' + (v ? '[' + v.join(', ') + ']' : '<array>'));
      clean++;
    }
    else if (kind === 'table') { lines.push('', name + ' = <table>'); clean++; }
    else if (dvmIsProse(seg) || dvmIsIdentifier(seg)) { lines.push('', name + ' = ' + JSON.stringify(str(seg))); clean++; }
    else { lines.push('', name + ' = <' + seg.length + ' bytes>'); failed++; }
  }
  const cls = dvmClassName(resid);
  const sym = resourceSymbol(resid);
  if (sym) lines.unshift('// name: ' + sym);
  lines.unshift('// ' + objs.length + ' objects: ' + clean + ' resolved, ' + failed + ' unresolved');
  if (cls) lines.unshift('// class: ' + cls + ' (resource 0x' + resid.toString(16).toUpperCase() + ')');
  return lines.join('\n');
}

// THE strings in a resource, read from the container rather than guessed at
// from the raw bytes. This exists because the guessing was demonstrably
// wrong: resource 0x1B01 is `00 9D 81 01 00 "The most interesting..."`, and a
// Pascal scan lands on the 'T', reads it as a length of 84 (0x54), and emits
// "he most interesting ... with a glowing tria" -- first letter eaten, cut off
// mid-word at exactly 84 characters -- then starts a fresh bogus string at the
// 'n' it left behind. The decoded view had it right the whole time; the
// preview and strings panes were running a completely different, dumber
// algorithm over the same bytes. Now there is one source of truth.
//
// The logic below deliberately mirrors dvmRender's, so a string shown in the
// preview is character-for-character the string shown in the disassembly.
function dvmStringObjects(b, resid) {
  const out = [];
  try {
    const objs = dvmExtents(b, resid);
    for (const [st, en, kind] of objs) {
      const seg = b.subarray(st, Math.min(en, b.length));
      if (!seg.length) continue;
      if (kind === 'function') {
        // A "function" whose body is prose up to the first NUL is a string
        // constant, which is how Delver stores most of its text.
        const body = seg.subarray(3);
        let z = -1;
        for (let i = 0; i < body.length; i++) if (body[i] === 0) { z = i; break; }
        const head = z > 0 ? body.subarray(0, z) : body;
        if (dvmIsProse(head)) {
          const t = decodeMacRoman(head.filter(c => c));
          if (t.trim()) out.push({ offset: st + 3, str: t, kind: 'delver' });
          continue;
        }
        // Most dialogue is not a standalone string object -- it is a `pushc`
        // operand inside a function, which only the disassembler can find.
        // Harvesting those is what keeps a character's lines from vanishing
        // when the naive Pascal scan is switched off.
        let r;
        try { r = dvmDisassemble(seg, 3); } catch (e) { continue; }
        for (const op of r.ops) {
          if (op[2] !== 'string' && op[2] !== 'string(implicit)') continue;
          let t;
          try { t = JSON.parse(op[3].replace(/ -> 0x[0-9A-F]{4}$/, '')); } catch (e) { continue; }
          if (t && t.trim() && /[A-Za-z]{2}/.test(t)) {
            out.push({ offset: st + op[0], str: t, kind: 'delver' });
          }
        }
      } else if (kind !== 'array' && kind !== 'table') {
        if (!(dvmIsProse(seg) || dvmIsIdentifier(seg))) continue;
        const t = decodeMacRoman(seg.filter(c => c));
        if (t.trim()) out.push({ offset: st, str: t, kind: 'delver' });
      }
    }
  } catch (e) {}
  return out;
}

function dvmOutboundRefs(b, resid) {
  const refs = [];
  const n = b ? b.length : 0;
  if (!n) return refs;
  const take = (off, w, via) => {
    if (w & 0x80000000) {
      // dref: 0x8000_0000 | resid<<16 | offset
      const r = (w & 0x7FFF0000) >>> 16;
      if (r && r !== resid) refs.push({ off, kind: 'dref', target: r, detail: '+0x' + (w & 0xFFFF).toString(16).toUpperCase(), via });
    } else if ((w >>> 28) === 3) {
      // resource word: 0x3 iii rrrr -- resource rrrr, array entry iii
      const r = w & 0xFFFF;
      if (r && r !== resid) refs.push({ off, kind: 'resource', target: r, detail: 'entry ' + ((w >>> 16) & 0xFFF), via });
    }
  };
  // A named script is a bare body with no container around it, and the body is
  // NOT Delver VM bytecode -- forcing the disassembler over it yields a stream
  // of bogus opcodes, and harvesting "references" from that would poison the
  // whole index with resources that do not exist. Report nothing until the
  // format is actually understood.
  if (typeof dvmNamedScript === 'function' && dvmNamedScript(b)) return refs;
  const { tableOffset, kinds } = dvmDiscover(b, resid);
  if (tableOffset === null) return refs;
  const offs = Object.keys(kinds).map(Number).sort((x, y) => x - y);
  // A dispatch table sits at tableOffset even when kindAt() called it data.
  if (tableOffset < n && offs.indexOf(tableOffset) === -1) offs.push(tableOffset);
  for (const off of offs) {
    const kind = (off === tableOffset) ? 'table' : kinds[off];
    if (kind === 'array' || kind === 'table') {
      const size = u16be(b, off) & 0x0FFF;
      const stride = (kind === 'table') ? 6 : 4;
      for (let i = 0, p = off + 2; i < size && p + 4 <= n; i++, p += stride) {
        take(p, u32be(b, p), kind);
      }
    } else if (kind === 'function') {
      // Slice to the next discovered offset so a function does not decode on
      // into the data that follows it, matching how dvmRender bounds bodies.
      let end = n;
      for (const o2 of offs) if (o2 > off && o2 < end) end = o2;
      let ops;
      try { ops = dvmDisassemble(b.slice(off, end), 3).ops; } catch (e) { continue; }
      for (const [at, , mn] of ops) {
        const a = off + at;
        if (mn === 'word' && a + 5 <= n) take(a, u32be(b, a + 1), 'code');
        else if (mn === 'call_resource' && a + 3 <= n) {
          const r = u16be(b, a+1);
          if (r && r !== resid) refs.push({ off: a, kind: 'call', target: r, detail: 'call_resource', via: 'code' });
        }
      }
    }
  }
  return refs;
}

// A one-line description of what the container actually holds, built from the
// same discovery pass the disassembler uses.
function dvmShapeSummary(b, resid) {
  try {
    if (dvmNamedScript(b)) return 'A named script: Pascal name followed by a non-bytecode body.';
    const objs = dvmExtents(b, resid);
    if (!objs.length) return 'No Delver container structure found.';
    const counts = {};
    for (const [, , kind] of objs) counts[kind] = (counts[kind] || 0) + 1;
    const bits = [];
    const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
    if (counts.function) bits.push(plural(counts.function, 'function'));
    if (counts.array) bits.push(plural(counts.array, 'array'));
    if (counts.table) bits.push(plural(counts.table, 'table'));
    if (counts.data) bits.push(plural(counts.data, 'data block'));
    return bits.length ? bits.join(', ') : 'One block of undecoded data.';
  } catch (e) { return 'Structure could not be determined.'; }
}
