import os
import json
import tempfile
import base64
import anthropic
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, TranscriptionUsage

transcribe_bp = Blueprint('transcribe', __name__)


# ── JSON safety ────────────────────────────────────────────────────────────
def _sanitise_json(s: str) -> str:
    """
    Claude occasionally emits literal control characters (real newlines,
    tabs, carriage returns) inside JSON string values instead of the
    escaped sequences \\n / \\t / \\r.  These are technically invalid JSON
    and cause json.loads to raise JSONDecodeError.

    This function walks the raw string character-by-character and replaces
    any bare control character found *inside* a JSON string with its
    correctly-escaped counterpart, leaving the structural characters
    (newlines between keys, etc.) untouched.
    """
    result = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == '\\' and in_string:
            result.append(ch)
            escape_next = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        else:
            result.append(ch)
    return ''.join(result)


# ── Whisper transcript post-corrections ───────────────────────────────────
# Whisper consistently mishears certain property-inspection terms.
# Apply these substitutions after transcription, before Claude sees the text.
import re as _re
_TRANSCRIPT_CORRECTIONS = [
    # Technical terms
    (_re.compile(r'\bcereal number\b', _re.I),    'serial number'),
    (_re.compile(r'\bserial numbers?\b', _re.I),  'serial number'),  # normalise
    (_re.compile(r'\bse real number\b', _re.I),   'serial number'),
    (_re.compile(r'\bsiren number\b', _re.I),     'serial number'),
    (_re.compile(r'\bwhite goods\b', _re.I),      'white goods'),    # keep as-is (just pin)
    # Common dictation mishearings
    (_re.compile(r'\bwarm and tare\b', _re.I),    'fair wear and tear'),
    (_re.compile(r'\bwhere and tare\b', _re.I),   'fair wear and tear'),
    (_re.compile(r'\bwear and tare\b', _re.I),    'fair wear and tear'),
    (_re.compile(r'\bfair wear and tear\b', _re.I), 'fair wear and tear'),  # pin
    (_re.compile(r'\bcoving\b', _re.I),           'coving'),
    (_re.compile(r'\bcorving\b', _re.I),          'coving'),
    (_re.compile(r'\bskirting board\b', _re.I),   'skirting board'),
    (_re.compile(r'\bskirting boards?\b', _re.I), 'skirting board'),
    (_re.compile(r'\barchitrave\b', _re.I),       'architrave'),
    (_re.compile(r'\bark it trave\b', _re.I),     'architrave'),
    (_re.compile(r'\binduction hob\b', _re.I),    'induction hob'),
    (_re.compile(r'\bextractor fan\b', _re.I),    'extractor fan'),
    (_re.compile(r'\bextractor\b', _re.I),        'extractor'),
    (_re.compile(r'\bthermostatic\b', _re.I),     'thermostatic'),
    (_re.compile(r'\bthermostat ic\b', _re.I),    'thermostatic'),
    (_re.compile(r'\bTRV\b', _re.I),              'TRV'),
    (_re.compile(r'\bdouble glazed\b', _re.I),    'double glazed'),
    (_re.compile(r'\bUPVC\b', _re.I),             'UPVC'),
    (_re.compile(r'\byou PVC\b', _re.I),          'UPVC'),
    (_re.compile(r'\bu PVC\b', _re.I),            'UPVC'),
    # Normalise compound words to standard UK one-word forms
    (_re.compile(r'\blime\s+scale\b', _re.I),     'limescale'),
    # Normalise "add sub-item" variants → canonical trigger phrase "add sub item"
    (_re.compile(r'\badd sub-items?\b', _re.I),   'add sub item'),
    (_re.compile(r'\badd subitems?\b', _re.I),    'add sub item'),
    (_re.compile(r'\badd a sub-?item\b', _re.I),  'add sub item'),
    # Normalise "not seen" variants (Whisper mishearing)
    (_re.compile(r'\bnot scene\b', _re.I),        'not seen'),
    # Normalise "delete item" variants (hyphen / spacing)
    (_re.compile(r'\bdelete-item\b', _re.I),      'delete item'),
]

def _correct_transcript(text: str) -> str:
    """Apply known Whisper mishearing corrections for property inspection vocabulary."""
    for pattern, replacement in _TRANSCRIPT_CORRECTIONS:
        text = pattern.sub(replacement, text)
    return text


# ── Inspection vocabulary dictionaries ────────────────────────────────────
# Injected into AI prompts so the model reliably recognises condition signals
# and description terms across all property inspection item types.

_CONDITION_WORDS = """
══════════════════════════════════════════════════════
CONDITION VOCABULARY — all recognised condition signals
══════════════════════════════════════════════════════
Everything below signals CONDITION, not description.
Once any of these appears, everything from that word onwards is condition.

State grades:
  In good order / Good order / In very good order / In excellent order / As new / As inventory / As found
  In fair order / Fair order / Some wear / Light wear / Light surface wear / Fair wear and tear
  In poor order / Poor order / Heavily worn / Well worn

Magnitude qualifiers (appear before a defect word — the whole phrase is condition):
  Light / Slight / Minor / Superficial / Moderate / Heavy / Severe / Extensive / Significant / Notable

Surface defects:
  Scuff / Scuffs / Scuffed / Scuffing / Light scuffing / Scuff mark / Scuff marks
  Scratch / Scratches / Scratched / Scratching / Light scratching / Surface scratching / Light surface scratching
  Mark / Marks / Marked / Marking / Light marking / Light marks / Light surface marks
  Chip / Chips / Chipped / Chipping / Small chip / Large chip
  Crack / Cracks / Cracked / Cracking / Hairline crack / Fine crack / Stress crack / Crazing
  Dent / Dents / Dented / Denting
  Gouge / Gouges / Gouged / Nick / Nicks / Nicked / Notch / Notches / Score / Scored
  Hole / Holes / Small hole / Large hole

Finish defects:
  Stain / Stains / Stained / Staining / Light staining / Tide mark / Water mark / Water stain
  Burn / Burns / Burned / Burnt / Burn mark / Scorch / Scorched / Scorching / Scorch mark
  Discolouration / Discoloured / Yellowing / Yellowed / Fading / Faded / Bleached

Surface deterioration:
  Peeling / Peeled / Peel / Paint peeling / Flaking / Flaked / Flake
  Bubbling / Bubbled / Blistering / Blistered
  Warping / Warped / Bowing / Bowed / Buckling / Buckled
  Sagging / Sagged / Splitting / Split / Tearing / Torn / Fraying / Frayed

Soiling:
  Dirty / Soiled / Grimy / Greasy / Dusty
  Mould / Mouldy / Mildew / Mildewed / Black mould
  Damp / Dampness / Water damage / Water ingress
  Limescale / Scale / Scaling / Scale build-up / Ingrained dirt

Metal defects:
  Rust / Rusted / Rusty / Rusting / Corrosion / Corroded / Corroding / Tarnished / Tarnishing / Pitting / Pitted

Hardware / fitting defects:
  Loose / Slightly loose / Very loose / Coming loose
  Tight / Stiff / Sticky / Binding / Catching / Difficult to operate / Sticking / Stuck / Seized / Jammed
  Missing / Absent / Not present
  Broken / Snapped / Fractured / Shattered
  Bent / Misaligned / Off-square / Dropped / Dropped hinge
  Rattling / Rattle / Squeaking / Squeak / Creaking / Creak / Damaged / Worn / Heavily worn

Grout & silicone:
  Cracked grout / Missing grout / Discoloured grout / Mouldy grout
  Failed silicone / Cracked silicone / Discoloured silicone / Mouldy silicone / Deteriorating silicone

Functional observations (always condition, never description):
  Tested / Tested for power / Tested for function / Tested and working / Working / Not working
  Appears working / Appears complete / Appear complete / Appears functional / Operated / Does not operate
  Note / Noted / Please note / Worth noting
"""

_DESCRIPTION_VOCABULARY = """
══════════════════════════════════════════════════════
DESCRIPTION VOCABULARY — recognised terms by item type
══════════════════════════════════════════════════════
Use this as a reference to correctly parse description content.
Always use the clerk's exact words — this list shows what typical descriptions contain.

DOORS & FRAMES:
  white painted / painted / stained / varnished / lacquered / natural / bare wood / MDF / solid wood /
  hollow core / pine / oak / hardwood / softwood / composite / fire door / FD30 / FD60 /
  flush / panelled / two-panel / four-panel / six-panel / glazed / part-glazed / frosted glass /
  half-glazed / fully glazed / stable door / bi-fold / sliding / French doors / double door / single door /
  architrave / door frame / door lining / door stop / threshold / draught excluder / UPVC frame /
  timber frame / aluminium frame

DOOR FITTINGS:
  lever handle / knob handle / D-handle / pull handle / bar handle / chrome / brushed chrome /
  satin chrome / brushed nickel / brass / antique brass / gold / black / pewter / white / stainless steel /
  latch / deadlock / mortice lock / rim lock / night latch / Yale lock / multipoint lock /
  euro cylinder / thumb turn / bathroom lock / WC lock / privacy lock /
  barrel bolt / flush bolt / security bolt / chain / door chain / door knob / escutcheon /
  kicking plate / kick plate / finger plate / push plate / self-closing mechanism /
  magnetic catch / roller catch / ball catch

CEILING:
  smooth plaster / plastered / artex / textured / Artex / coving / cornicing / cornice / ceiling rose /
  polystyrene tiles / suspended / plasterboard / painted / white / cream / emulsion /
  loft hatch / loft access / trap door / attic hatch / access panel / bulkhead / boxed-in /
  recessed / flat / vaulted / sloped / pitched / slanted

LIGHTING:
  pendant light / pendant fitting / ceiling light / ceiling fitting / light fitting / wall light /
  spotlight / recessed spotlight / recessed light / downlight / batten light / strip light /
  fluorescent light / LED strip / track lighting / chandelier / lantern / reading light /
  PIR light / motion sensor light / lampshade / shade / diffuser / glass shade / fabric shade /
  drum shade / globe / flex / rose / pull cord / dimmer switch / bulb / LED bulb /
  bayonet / BC / screw fit / GU10 / halogen

WALLS:
  painted / emulsion / matt emulsion / silk emulsion / satin / gloss / painted plaster /
  wallpaper / patterned wallpaper / plain wallpaper / woodchip / vinyl wallpaper /
  feature wall / tiled / part-tiled / panelled / tongue and groove / wainscot /
  dado rail / picture rail / artex / textured finish / smooth plaster / dry-lined / skim coat /
  white / cream / magnolia / off-white / grey / light grey / beige / neutral

WINDOWS & FRAMES:
  UPVC / timber / softwood / hardwood / oak / pine / aluminium / steel / composite /
  painted / white / brown / anthracite / grey / black / natural / stained / varnished /
  double glazed / triple glazed / single glazed / obscure / frosted / safety glass / toughened glass /
  sealed unit / misted unit / Georgian bar / leaded glass /
  handle / espagnolette handle / locking handle / sash lock / cockspur handle /
  stay / casement stay / sash lift / friction stay / trickle vent / ventilator /
  casement / sash / sash and case / tilt and turn / bay window / bow window /
  skylight / Velux / roof light / dormer / fixed light / transom / fanlight

CURTAINS & BLINDS:
  curtain / curtains / pair of curtains / single curtain / tab top / eyelet / pencil pleat /
  pinch pleat / ring top / voile / net curtain / lining / unlined / blackout / thermal /
  curtain rail / curtain pole / wooden pole / metal pole / chrome pole / track / pelmet /
  valance / bay pole / fascia / finial / bracket / ring / runner /
  roller blind / Roman blind / Venetian blind / vertical blind / pleated blind / cellular blind /
  blackout blind / wooden blind / timber blind / aluminium blind / fabric blind /
  fabric / linen / cotton / polyester / velvet / patterned / plain / striped / floral

HEATING:
  radiator / panel radiator / column radiator / towel radiator / heated towel rail /
  ladder towel rail / single panel / double panel / single convector / double convector /
  compact radiator / low surface temperature / LST radiator /
  TRV / thermostatic radiator valve / lock shield valve / wheelhead / manual valve /
  electric panel heater / storage heater / underfloor heating / UFH / thermostat /
  combi boiler / water cylinder / pressurised cylinder / immersion heater /
  boiler cupboard / airing cupboard / room thermostat / Hive / Nest / smart thermostat

BUILT-IN STORAGE:
  fitted wardrobe / built-in wardrobe / wardrobe / sliding wardrobe / sliding door wardrobe /
  fitted cupboard / built-in cupboard / alcove cupboard / understairs cupboard / airing cupboard /
  larder cupboard / pantry / linen cupboard / fitted shelving / alcove shelving / fitted bookcase /
  shelf / shelves / hanging rail / hanging space / rail / hook / hooks / drawer / drawers /
  sliding door / mirrored door / mirror door / internal light / basket / wire basket / divider /
  white / painted / MDF / pine / gloss / matt / mirror / mirrored / smoked mirror / glass

SWITCHES & SOCKETS:
  single socket / double socket / twin socket / USB socket / USB-A / USB-C /
  coaxial socket / TV aerial socket / telephone socket / data socket / ethernet socket /
  satellite socket / shaver socket / shaver point /
  light switch / single switch / double switch / dimmer switch / timer switch /
  pull cord / ceiling pull cord / isolator switch / extractor fan switch / fused spur /
  consumer unit / fuse box / MCB / RCD / RCBO / circuit breaker / fuse board /
  electric meter / gas meter / smart meter /
  white / chrome / brushed chrome / nickel / brushed nickel / brass / black / stainless steel / flat plate

WOODWORK:
  skirting board / skirting / architrave / door architrave / window board / window sill /
  window reveal / dado rail / picture rail / coving / cornice / beading / ovolo / torus /
  ogee / bullnose / half-round / chamfered / pencil round / quad / Scotia / batten /
  shelf / shelving / mantelpiece / mantel / chimney breast / fireplace surround /
  painted / gloss / satinwood / eggshell / primer / undercoat / white / cream /
  wood-stained / varnished / natural / bare / stripped / MDF / pine / hardwood

FLOORING:
  carpet / fitted carpet / carpet tile / laminate / laminate flooring / engineered wood /
  engineered hardwood / solid hardwood / parquet / parquet flooring / herringbone /
  luxury vinyl tile / LVT / vinyl / sheet vinyl / safety vinyl /
  ceramic tile / floor tile / porcelain tile / encaustic tile / quarry tile / stone tile /
  slate / travertine / marble / natural stone / resin / polished concrete /
  underlay / gripper rod / threshold / door bar / transition strip / metal threshold /
  silver threshold / brass threshold / inlay / border / rug / mat / doormat

FURNITURE:
  bed / single bed / double bed / king size bed / super king bed / divan / bed frame / headboard /
  ottoman / chest of drawers / dressing table / bedside table / bedside cabinet / wardrobe /
  free-standing wardrobe / mirror / full-length mirror / blanket box / bunk bed /
  sofa / two-seater sofa / three-seater sofa / corner sofa / L-shaped sofa /
  armchair / chair / recliner / footstool / coffee table / side table / occasional table /
  TV unit / media unit / entertainment unit / bookcase / shelving unit / sideboard /
  display cabinet / dining table / dining chair / dining set / desk / office chair / filing cabinet /
  coat rack / coat stand / hat stand / umbrella stand / picture / artwork / print / clock /
  wood / solid wood / pine / oak / walnut / beech / MDF / painted / lacquered /
  upholstered / fabric / leather / faux leather / velvet / rattan / wicker / metal / steel / glass

SINK & TAPS:
  ceramic sink / stainless steel sink / butler sink / Belfast sink / farmhouse sink /
  single bowl sink / double bowl sink / 1.5 bowl sink / inset sink / undermount sink /
  drainer / draining board / integral draining board / waste / plug hole /
  kitchen tap / mixer tap / single lever tap / two-handle tap / pillar tap / monobloc tap /
  pullout tap / spray tap / boiling water tap / filter tap / Quooker /
  Grohe / Hansgrohe / Franke / Armitage Shanks /
  chrome / brushed chrome / brushed nickel / black / brushed brass / gold / gunmetal / white

KITCHEN WALL UNITS:
  wall unit / wall cabinet / wall cupboard / eye-level unit / larder unit /
  single door wall unit / double door wall unit / corner wall unit / glass door unit /
  display unit / wine rack / plate rack / open shelf unit /
  shelf / shelves / door / doors / glass door / soft-close hinge / bar handle / knob /
  integrated handle / push-to-open / push latch

KITCHEN BASE UNITS:
  base unit / base cabinet / floor unit / cupboard / larder unit / larder cupboard /
  pan drawer / drawer pack / three-drawer pack / four-drawer pack / corner base unit /
  pull-out unit / carousel / lazy Susan / sink unit / hob unit / tall unit / tower unit /
  oven housing / oven tower / pantry unit / integrated appliance unit /
  shelf / shelves / door / doors / drawer / drawers / soft-close drawer / soft-close door /
  bar handle / D-handle / knob / integrated handle / push-to-open /
  gloss / matt / satin / handleless / shaker / slab / in-frame / painted /
  white / grey / cream / navy / sage green / blue / black / walnut effect / oak effect / high gloss /
  plinth / kickboard / kick board / toe kick / plinth panel /
  white carcass / grey carcass / birch carcass

WORKTOPS:
  laminate worktop / laminate / solid wood worktop / oak worktop / beech worktop / walnut worktop /
  bamboo worktop / granite worktop / granite / marble worktop / marble /
  quartz worktop / quartz / Corian / solid surface / composite worktop /
  ceramic worktop / porcelain worktop / stainless steel worktop / compact laminate /
  upstand / splashback / matching upstand / worktop upstand /
  square edge / post-formed edge / bullnose edge / bevelled edge / waterfall edge / mitre joint / end cap

SMOKE ALARMS:
  smoke alarm / smoke detector / optical smoke alarm / ionisation smoke alarm /
  heat alarm / heat detector / combined smoke and heat alarm / interlinked alarm /
  mains-powered alarm / battery-powered alarm / sealed battery alarm / 10-year alarm /
  Aico / Kidde / FireAngel / BRK / First Alert / Nest Protect / Google Nest /
  Honeywell / Hochiki / EI Electronics / ESP / Ei650 / Ei3016

CARBON MONOXIDE ALARMS:
  carbon monoxide alarm / CO alarm / CO detector / carbon monoxide detector /
  combined smoke and CO alarm / interlinked CO alarm / mains CO alarm / battery CO alarm /
  Aico / Kidde / FireAngel / BRK / First Alert / Nest Protect / Google Nest /
  Honeywell / Ei208 / Ei3018

WASH BASINS:
  wash basin / basin / pedestal basin / hand basin / semi-pedestal basin /
  wall-mounted basin / countertop basin / vessel basin / inset basin / undermount basin /
  corner basin / cloakroom basin / small basin /
  ceramic / vitreous china / china / white /
  basin tap / mixer tap / monobloc / pillar tap / single lever / waterfall tap /
  pop-up waste / plug and chain waste / slotted waste / overflow /
  Grohe / Hansgrohe / Armitage Shanks / Ideal Standard / Roca / Duravit / Villeroy & Boch /
  pedestal / half pedestal / cloakroom shelf / vanity unit / mirror cabinet

TOILETS:
  toilet / WC / close coupled WC / back to wall WC / wall-hung WC / wall-hung toilet /
  floor-standing WC / low-level WC / high-level WC /
  concealed cistern / slimline cistern / compact WC / cloakroom WC /
  cistern / pan / seat / seat and cover / soft-close seat / quick-release seat /
  flush button / dual flush / flush plate / flush handle / flush lever / overflow pipe /
  Ideal Standard / Armitage Shanks / Roca / Duravit / Villeroy & Boch /
  RAK Ceramics / Geberit / Grohe / Hansgrohe / VitrA /
  white / cream / ceramic / vitreous china

BATH & TAPS:
  bath / bathtub / roll top bath / freestanding bath / slipper bath / straight bath /
  single-ended bath / double-ended bath / P-shaped bath / L-shaped bath / corner bath /
  whirlpool bath / shower bath / bath panel / side panel / end panel /
  bath tap / bath taps / bath mixer / bath filler / floor-standing bath tap /
  wall-mounted bath tap / overflow filler / deck-mounted / freestanding tap / pillar tap /
  shower handset / bath shower mixer / shower attachment / telephone handset /
  acrylic / steel enamel / cast iron / stone resin / solid surface /
  Ideal Standard / Armitage Shanks / Carron / Trojan / BC Designs / Victoria and Albert /
  Duravit / Villeroy & Boch / Roca / Hudson Reed / Grohe / Hansgrohe / Crosswater

SHOWER & SCREENS:
  shower enclosure / shower cubicle / walk-in shower / walk-in enclosure /
  wet room / corner shower / quadrant shower / offset quadrant / rectangular enclosure /
  pivot door / sliding door / hinged door / bi-fold door / frameless / semi-frameless / framed /
  shower tray / stone resin tray / acrylic tray / ceramic tray / low-profile tray /
  flush tray / wetroom former / linear drain / central drain /
  shower screen / bath screen / fixed screen / folding screen / hinged screen /
  shower head / fixed head / rainfall head / ceiling-mounted head / handset / shower handset /
  hose / slide rail / shower bar / thermostatic valve / thermostatic shower /
  mixer shower / electric shower / digital shower / smart shower /
  Mira / Triton / Aqualisa / Grohe / Hansgrohe / Crosswater / Hudson Reed /
  Matki / Lakes / Kudos / Roman / Daryl / Bristan / Roca / Ideal Standard / Merlyn / April

APPLIANCES (built-in & free-standing):
  oven / built-in oven / single oven / double oven / multifunction oven /
  fan oven / electric oven / gas oven / pyrolytic oven / steam oven / warming drawer /
  hob / gas hob / electric hob / induction hob / ceramic hob / solid plate hob /
  four burner / five burner / six burner / gas burner / burner / zone / ring /
  extractor / extractor fan / cooker hood / chimney hood / island hood /
  integrated extractor / canopy / air recirculation / ducted / carbon filter / grease filter /
  dishwasher / integrated dishwasher / freestanding dishwasher / slimline dishwasher /
  washing machine / integrated washing machine / washer-dryer / tumble dryer /
  condenser dryer / heat pump dryer / vented dryer / integrated dryer /
  fridge / refrigerator / fridge-freezer / American fridge-freezer / freezer /
  chest freezer / larder fridge / wine cooler / wine fridge / integrated fridge /
  integrated fridge-freezer / integrated freezer / under-counter fridge /
  microwave / combination microwave / grill microwave / built-in microwave /
  integrated coffee machine / plate warmer /
  Bosch / Siemens / Samsung / LG / Hotpoint / Indesit / Beko / Zanussi /
  AEG / Miele / Neff / Whirlpool / Smeg / Rangemaster / Lacanche / Falcon / Aga / Rayburn /
  Fisher & Paykel / Haier / Hisense / Electrolux / Liebherr / Sub-Zero / Wolf / Viking /
  Gaggenau / Bauknecht / Candy / Hoover / Stoves / Britannia / Leisure / Blomberg / Lamona /
  Baumatic / Bertazzoni / CDA

SMALL APPLIANCES:
  kettle / toaster / air fryer / blender / food processor / coffee machine / espresso machine /
  Nespresso / Dolce Gusto / stand mixer / hand mixer / hand blender / stick blender /
  bread maker / rice cooker / slow cooker / instant pot / pressure cooker / steamer /
  juicer / smoothie maker / sandwich maker / griddle / waffle maker / deep fat fryer /
  electric grill / health grill / George Foreman / vacuum cleaner / steam cleaner / steam mop /
  robot vacuum / iron / steam iron / clothes steamer / fan / tower fan / pedestal fan / desk fan /
  oil-filled radiator / fan heater / dehumidifier / air purifier / humidifier /
  Kenwood / Breville / Dualit / Russell Hobbs / DeLonghi / KitchenAid / Dyson / Shark /
  Morphy Richards / Tefal / Philips / Braun / Sage / Nutribullet / Vitamix / Magimix / Cuisinart

BATHROOM ACCESSORIES:
  towel rail / towel ring / towel bar / robe hook / coat hook /
  toilet roll holder / toothbrush holder / soap dish / soap dispenser /
  shower basket / corner shelf / glass shelf / mirror / bathroom mirror / medicine cabinet /
  shaver socket / shaver light / extractor fan / bathroom cabinet / vanity unit /
  under-sink unit / toilet brush / toilet brush holder /
  chrome / brushed chrome / nickel / brushed nickel / brass / antique brass /
  black / gunmetal / gold / white / stainless steel
"""


# ── Edit-mode detection ────────────────────────────────────────────────────
# Clerks can prefix a recording with trigger phrases to amend existing fields
# rather than filling only-if-empty.
#
# Supported commands (per-item / Instant mode):
#   "Not Applicable"         → mark item for deletion
#   "Add sub item ..."       → add a sub-item beneath the current item
#   "Amend description ..."  → overwrite description field only
#   "Amend condition ..."    → overwrite condition field only
#   "Add to description ..." → append to description field only
#   "Add to condition ..."   → append to condition field only
#   "Amend ..."              → overwrite both fields (item context is implicit)
#   "Add ..."                → append to both fields
#
# NOTE: longer/more specific phrases must come before short ones so they match first.

_EDIT_TRIGGERS = [
    # Delete commands — item is not in the property or not applicable
    ('not seen',               'delete',    None),
    ('not scene',              'delete',    None),   # common Whisper mishearing of "not seen"
    ('delete item',            'delete',    None),
    ('not applicable',         'delete',    None),
    # Sub-item command — treat transcript content as a new sub-item
    ('add sub item',           'add_sub',   None),
    # Specific field amend/add
    ('amend description',      'overwrite', 'description'),
    ('amend the description',  'overwrite', 'description'),
    ('amend condition',        'overwrite', 'condition'),
    ('amend the condition',    'overwrite', 'condition'),
    ('add to description',     'append',    'description'),
    ('add to the description', 'append',    'description'),
    ('add to condition',       'append',    'condition'),
    ('add to the condition',   'append',    'condition'),
    ('add to conditions',      'append',    'condition'),
    ('add to the conditions',  'append',    'condition'),
    # Short forms — for Instant mode where item context is implicit
    ('amend',                  'overwrite', None),
    ('add',                    'append',    None),
]

def _detect_edit_mode(transcript: str):
    """
    Check if transcript starts with an edit-mode trigger phrase.
    Returns (mode, field, cleaned_transcript).
      mode:    'overwrite' | 'append' | 'delete' | 'add_sub' | 'normal'
      field:   'description' | 'condition' | None
      cleaned: transcript with trigger phrase stripped
    """
    lower = transcript.lower().strip()
    for phrase, mode, field in _EDIT_TRIGGERS:
        if lower.startswith(phrase):
            cleaned = transcript[len(phrase):].lstrip(' ,.:-').strip()
            return mode, field, cleaned
    return 'normal', None, transcript


# ── Helpers ────────────────────────────────────────────────────────────────

def _whisper_transcribe(audio_bytes: bytes, mime_type: str) -> tuple[str, float]:
    """
    Send audio bytes to OpenAI Whisper, return (transcript, duration_seconds).
    Uses verbose_json to get actual duration rather than estimating from byte count.
    """
    import openai

    client = openai.OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

    ext_map = {
        'audio/webm':  'webm',
        'audio/ogg':   'ogg',
        'audio/mp4':   'mp4',
        'audio/mpeg':  'mp3',
        'audio/mp3':   'mp3',
        'audio/wav':   'wav',
        'audio/x-wav': 'wav',
        'audio/flac':  'flac',
        'audio/m4a':   'm4a',
        'audio/aac':   'm4a',
        'video/webm':  'webm',  # some browsers report video/webm for audio
    }
    # Strip codec suffix e.g. "audio/webm;codecs=opus" → "audio/webm"
    mime_base = mime_type.split(';')[0].strip().lower() if mime_type else 'audio/webm'
    ext = ext_map.get(mime_base, 'webm')
    print(f'[transcribe] mime_base: {repr(mime_base)} → ext: {ext}')

    with tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, 'rb') as f:
            response = client.audio.transcriptions.create(
                model='whisper-1',
                file=f,
                language='en',
                response_format='verbose_json',
                prompt=(
                    'UK property inventory inspection dictation. '
                    'Speaker describes item appearance and condition. '
                    'Key vocabulary: serial number, skirting board, coving, architrave, '
                    'induction hob, extractor fan, UPVC, double glazed, thermostatic, TRV, '
                    'fair wear and tear, in good order, in fair order, in poor order. '
                    'Commands to preserve exactly: '
                    '"Delete item", "Not Applicable", "Not seen", "Add sub item", '
                    '"Amend description", "Amend condition", '
                    '"Add to description", "Add to condition", "Amend", "Add". '
                    'Transcribe all words accurately, including technical property terms.'
                )
            )
        raw_transcript = str(response.text).strip()
        duration_seconds = float(response.duration or 0)
        return _correct_transcript(raw_transcript), duration_seconds
    finally:
        os.unlink(tmp_path)


def _claude_fill_item(transcript: str, item_label: str, room_name: str, section_type: str = 'room', edit_mode: str = 'normal', is_check_out: bool = False, is_damage_report: bool = False) -> dict:
    """
    Given a short transcript for a single item, return the appropriate fields
    based on section type. Uses claude-haiku-4-5.

    Section types and their fields:
    - room (default):        { description, condition }
    - condition_summary:     { condition }
    - cleaning_summary:      { notes }
    - fire_door_safety:      { notes }
    - health_safety:         { notes }
    - keys:                  { description }
    - meter_readings:        { locationSerial, reading }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    # ── Check-out per-item mode — verbatim, no splitting ───────────────────────
    # The mobile side handles the "As Inventory+" prefix; we just need the
    # clerk's exact words returned in "condition" with fillers removed.
    if is_check_out and section_type == 'room':
        co_prompt = f"""You are processing a UK property CHECK-OUT inspection dictation.
The clerk is describing the condition of a single item at the END of the tenancy.

Item: {item_label}
Room: {room_name}

The clerk said:
"{transcript}"

VERBATIM RULES — absolute, no exceptions:
- Return the COMPLETE transcript in "condition", exactly as spoken
- ONLY remove filler sounds: um, uh, er, errr, umm, erm, and clear false starts (e.g. "white — white door" → "white door")
- Do NOT interpret, condense, split, or restructure anything
- Do NOT apply description/condition splitting — everything goes into "condition"
- Convert spoken numbers to numerals: "two" → "2", "three" → "3"
- Format quantities as "N x item": "two bulbs" → "2 x bulbs"
- Capitalise the first word of each observation
- USE UK ENGLISH SPELLING — this is a legal document for UK property: "discolouration" not "discoloration",
  "colour" not "color", "centre" not "center", "neighbour" not "neighbor",
  "recognise" not "recognize", "labelled" not "labeled", "mould" not "mold"
- SEPARATE OBSERVATIONS ON DIFFERENT LINES: if the clerk mentions two or more distinct observations
  about different parts or fittings of the same item, put each observation on its own line using \\n
  NEVER join separate observations with a comma — use \\n instead
  Example: "handles slightly loose, one screw missing to interior handle"
    CORRECT:   "Handles slightly loose\\nOne screw missing to interior handle"
    INCORRECT: "Handles slightly loose, one screw missing to interior handle"
  A single observation about one thing may still use commas within that one line

Return ONLY valid JSON, no markdown:
{{"condition": "..."}}"""
        message = client.messages.create(
            model='claude-haiku-4-5',
            max_tokens=200,
            messages=[{'role': 'user', 'content': co_prompt}]
        )
        raw = message.content[0].text.strip()
        raw = raw.replace('```json', '').replace('```', '').strip()
        return json.loads(_sanitise_json(raw)), message

    # ── Damage Report per-item mode — verbatim, condition only ─────────────────
    if is_damage_report and section_type == 'room':
        dmg_prompt = f"""You are processing a UK property DAMAGE REPORT inspection dictation.
The clerk is describing the damage to a single item.

Item: {item_label}
Room: {room_name}

The clerk said:
"{transcript}"

RULES — absolute, no exceptions:
- Return the COMPLETE transcript in "condition" — there is NO description field in a damage report
- ONLY remove filler sounds: um, uh, er, errr, umm, erm, and clear false starts
- Do NOT interpret, condense, or paraphrase — use the clerk's exact words
- Convert spoken numbers to numerals: "two" → "2", "three" → "3"
- Format quantities as "N x item": "two marks" → "2 x marks"
- Capitalise the first word of each line
- USE UK ENGLISH SPELLING — this is a legal document for UK property: "discolouration" not "discoloration",
  "colour" not "color", "centre" not "center", "mould" not "mold"
- SEPARATE OBSERVATIONS ON DIFFERENT LINES: if the clerk mentions two or more distinct damage
  observations, put each on its own line using \\n. NEVER join with commas.
  Example: "scuff to bottom panel, chip to frame edge"
    CORRECT:   "Scuff to bottom panel\\nChip to frame edge"
    INCORRECT: "Scuff to bottom panel, chip to frame edge"
  A single observation about one location may use commas within that line.

Return ONLY valid JSON, no markdown:
{{"condition": "..."}}"""
        message = client.messages.create(
            model='claude-haiku-4-5',
            max_tokens=200,
            messages=[{'role': 'user', 'content': dmg_prompt}]
        )
        raw = message.content[0].text.strip()
        raw = raw.replace('```json', '').replace('```', '').strip()
        return json.loads(_sanitise_json(raw)), message

    # Shared formatting rules applied to all section types
    formatting_rules = """
FORMATTING RULES — apply to all output fields:
- Convert spoken numbers to numerals: "two" → "2", "three" → "3", "one" → "1" etc.
- Format quantities as "N x item": "two green curtains" → "2 x green curtains"
- When multiple distinct items are listed, put each on its own line
- For meter readings location: use line breaks for clarity, e.g.:
    "Located to entrance hallway cupboard\nSerial Number: 123456"
- Capitalise the first word of each line
- Do NOT use bullet points or dashes — just line breaks between items
- Keep each line concise"""

    if section_type == 'meter_readings':
        field_instructions = """Extract into these two fields:
- locationSerial: where the meter is located and its serial number, formatted across lines:
    "Located to [location]\nSerial Number: [number]"
  If only location mentioned, just the location. If only serial, just the serial.
- reading: the meter reading value only (e.g. "12345")
Return ONLY valid JSON, no markdown:
{"locationSerial": "...", "reading": ""}"""

    elif section_type == 'cleaning_summary':
        field_instructions = """Put the complete transcript (cleaned of filler words only) into cleanlinessNotes.
If multiple points are made, put each on its own line using \n.
Return ONLY valid JSON, no markdown:
{"cleanlinessNotes": "..."}"""

    elif section_type in ('fire_door_safety', 'health_safety', 'smoke_alarms'):
        field_instructions = """Put the complete transcript (cleaned of filler words only) into notes.
If multiple points are made, put each on its own line using \n.
Return ONLY valid JSON, no markdown:
{"notes": "..."}"""

    elif section_type == 'condition_summary':
        field_instructions = """Put the complete transcript (cleaned of filler words only) into condition.
If multiple points are made, put each on its own line.
Return ONLY valid JSON, no markdown:
{"condition": "..."}"""

    elif section_type == 'keys':
        field_instructions = """Put the complete transcript into the description field.
Format rules:
- If the clerk mentions anything about collecting, receiving, handing over, or returning keys — regardless of who from or to — put this EXACTLY as spoken on the FIRST line. This line must always be included when the clerk says it.
  Examples: "Keys collected from and returned to Yellands Estates", "Keys handed to tenant", "Keys received from landlord", "Keys collected from client and returned to office"
- Each key type goes on its own line using \\n, formatted as "N x [key type]"
  Example: "1 x Yale key\\n1 x Chubb key\\n2 x garage fob"
- Convert spoken numbers to numerals: "one" → "1", "two" → "2"
- Use "x" not "×" for quantities
Return ONLY valid JSON, no markdown:
{"description": "..."}"""

    else:
        # "Add sub item" mode — clerk is adding a sub-item to an existing item.
        # Parse description and condition from the transcript and return them
        # nested inside a _subs array so the caller knows to append, not overwrite.
        if edit_mode == 'add_sub':
            field_instructions = """The clerk is dictating a SUB-ITEM to add beneath an existing inspection item.
Extract description and condition from the transcript exactly as you would for a normal item,
then return the result inside a "_subs" array with a single entry.

Defect and state words are ALWAYS condition even when they appear without a preceding "in … order" phrase.
  Example: "chrome doorstop, slightly loose"
    → description: "Chrome doorstop"   condition: "Slightly loose"
  Example: "white door handle, missing screw"
    → description: "White door handle"   condition: "Missing screw"

If no condition is mentioned, default condition to "In good order".

MULTI-COMPONENT FORMATTING — CRITICAL: use \\n not commas to separate components or observations:
  CORRECT:   "White painted door\\nChrome handle"   condition: "In good order\\nLight scuffing to base"
  INCORRECT: "White painted door, chrome handle"   condition: "In good order, light scuffing to base"
  Commas are only acceptable within a single observation (e.g. "Scuff to base of door, left side").

""" + _CONDITION_WORDS + """
Return ONLY valid JSON, no markdown:
{"_subs": [{"description": "...", "condition": "..."}]}"""
        else:
            field_instructions = """Extract and structure this into:
- description: the physical appearance (material, colour, size, style, finish)
- condition: the state or working order

SPLITTING rules — read carefully:
- These phrases signal the START of the condition portion:
    "in good order", "in fair order", "in poor order", "good order", "fair order",
    "poor order", "as new", "as inventory", "in good condition", "in fair condition",
    "in poor condition", "some wear", "light wear", "heavy wear", "light scratches",
    "light marks", "light staining", "light surface", "surface scratching",
    "tested", "working", "functional", "appears", "appear", "note", "noted",
    "please note", "fair wear and tear"
- Everything AFTER a condition phrase is ALSO condition, not description.
  Example: "Black Beko induction hob, four burners, light surface scratching to hob plate"
    description: "Black Beko induction hob\n4 x burners"
    condition:   "Light surface scratching to hob plate"
- Functional observations ("appear complete", "tested for power", "appears working",
  "note scuff", "please note") are ALWAYS condition, never description
- Damage, marks, scratches, staining, wear = condition
- If the transcript contains ANY condition observations, use them — do NOT substitute "In good order"
- ONLY use "In good order" as a default if the clerk genuinely said nothing about condition AND
  there are no wear, damage, or observation words present

DEFAULT CONDITION RULE — this is critical:
- "In good order" is a fallback ONLY when zero condition information exists
- If the clerk said ANYTHING about appearance quality, wear, damage, or function — use their words
- WRONG: clerk says "light surface scratching" → condition: "In good order"
- RIGHT: clerk says "light surface scratching" → condition: "Light surface scratching"

MULTI-COMPONENT FORMATTING — CRITICAL: use \\n not commas to separate items:
- If description has multiple distinct physical components, put EACH on its own line using \\n
- A "component" is a distinct element — different surface, fitting, or object
- ALWAYS use \\n, NEVER commas to separate components or observations
  Example: "part white ceramic tile, part grey fitted carpet with silver metal threshold"
    CORRECT:   "Part white ceramic tile\\nPart grey fitted carpet\\nSilver metal threshold"
    INCORRECT: "Part white ceramic tile, part grey fitted carpet with silver metal threshold"
  Example: "dark wood curtain rail, two green fabric floor length curtains"
    CORRECT:   "Dark wood curtain rail\\n2 x green fabric floor length curtains"
    INCORRECT: "Dark wood curtain rail, two green fabric floor length curtains"
- Same rule applies to condition — multiple observations MUST each get their own line:
  Example: "in good order, light indentations to tiles, light wear to carpet"
    CORRECT:   "In good order\\nLight indentations to tiles\\nLight wear to carpet"
    INCORRECT: "In good order, light indentations to tiles, light wear to carpet"
- THE RULE: if you would use a comma between two separate ideas or observations, use \\n instead.
  Commas are only acceptable WITHIN a single observation (e.g. "Light scuff to base of door, left side")

APPLIANCE FORMATTING — for any appliance (washing machine, dishwasher, fridge, oven, hob, dryer, microwave, etc.):
- Each attribute MUST be on its own line — NEVER merge them into a single line
- Order: appliance type, then colour and brand, then model number, then serial number
  CORRECT:   "Washing machine\\nWhite Indesit\\nModel number: WD1234\\nSerial number: AB5678"
  INCORRECT: "White Indesit washing machine, model number WD1234, serial number AB5678"
- Format spoken model/serial references as "Model number: X" and "Serial number: X"
""" + _CONDITION_WORDS + """
Return ONLY valid JSON, no markdown:
{"description": "...", "condition": "..."}"""

    prompt = f"""You are processing a UK property inspection dictation.

Section type: {section_type}
Item: {item_label}
Room/Section: {room_name}

The clerk has dictated:
"{transcript}"

CRITICAL LANGUAGE RULES:
- Use the EXACT words and phrases the clerk spoke. Do not substitute synonyms, paraphrase, or condense.
- "good order" stays "good order" — never change to "good condition"
- "fair wear and tear" stays exactly that
- This is a legal document — preserve all professional terminology exactly
- ONLY remove filler sounds (um, uh, er, errr, umm, erm) — do NOT remove, shorten, or alter any actual content words
- Do NOT summarise or abbreviate what the clerk said — reproduce their words in full
- USE UK ENGLISH SPELLING THROUGHOUT — mandatory for every word in the output:
  "discolouration" not "discoloration", "colour" not "color", "centre" not "center",
  "neighbour" not "neighbor", "recognise" not "recognize", "labelled" not "labeled",
  "mould" not "mold", "grey" not "gray", "practise" not "practice" (verb)
{formatting_rules}

{field_instructions}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=300,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    return json.loads(_sanitise_json(raw)), message

def _claude_fill_full_report(transcript: str, template_structure: dict) -> dict:
    """
    Given a long continuous transcript covering a whole inspection,
    fill all items in the template structure.

    Returns a dict matching reportData shape:
    { sectionId: { rowId: { description: "...", condition: "..." } } }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    structure_json = json.dumps(template_structure, indent=2)

    prompt = f"""You are processing a UK property inventory inspection audio transcript.
The clerk has walked through the property and dictated descriptions and conditions for items room by room.

Template structure (the items that need filling):
{structure_json}

Full transcript:
"{transcript}"

Instructions:
- Map the clerk's dictation to the correct items in the template
- For each item, extract description and condition
- CRITICAL: Use the EXACT words and phrases the clerk spoke. Do not substitute synonyms or rephrase.
  Example: if the clerk says "good order", write "Good order" — NOT "Good condition"
  Example: if the clerk says "fair wear and tear", write exactly that
  Example: if the clerk says "as new" or "as inventory", preserve those exact phrases
- The clerk's terminology is professional and intentional — this is a legal document
- ONLY remove filler sounds (um, uh, er, errr, umm, erm) — do NOT remove, shorten, or alter any actual content words
- Do NOT summarise or abbreviate what the clerk said — reproduce their words in full
- USE UK ENGLISH SPELLING THROUGHOUT — every word in your output: "discolouration" not "discoloration",
  "colour" not "color", "mould" not "mold", "grey" not "gray", "centre" not "center"
- MULTI-COMPONENT FORMATTING: when description or condition has multiple distinct components or observations,
  separate each with \\n — NEVER use commas to join them.
  CORRECT:   "White painted door\\nChrome handle"   condition: "In good order\\nLight scuffing to base"
  INCORRECT: "White painted door, chrome handle"   condition: "In good order, light scuffing to base"
- Only fill items that are mentioned in the transcript
- If an item is not mentioned, omit it from the output entirely

Return ONLY valid JSON in this exact shape (no markdown):
{{
  "<sectionId>": {{
    "<rowId>": {{
      "description": "...",
      "condition": "..."
    }}
  }}
}}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=4000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    return json.loads(_sanitise_json(raw))


# ── Endpoints ─────────────────────────────────────────────────────────────

@transcribe_bp.route('/classify-photo', methods=['OPTIONS'])
def classify_photo_options():
    return '', 204


@transcribe_bp.route('/status', methods=['GET'])
@jwt_required()
def transcribe_status():
    """Returns which AI services are configured — used by TranscriptionSettings."""
    return jsonify({
        'openai':    'ok' if os.environ.get('OPENAI_API_KEY')    else 'missing',
        'anthropic': 'ok' if os.environ.get('ANTHROPIC_API_KEY') else 'missing',
    })


@transcribe_bp.route('/item', methods=['POST'])
@jwt_required()
def transcribe_item():
    """
    Per-item clip — called immediately when a short item recording stops.

    Request JSON:
    {
      "audio":      "<base64-encoded audio>",
      "mimeType":   "audio/webm",
      "itemLabel":  "Door & Frame",
      "roomName":   "Kitchen",
      "sectionId":  "abc123",
      "rowId":      "456"
    }

    Response JSON:
    {
      "transcript":  "White painted panel door...",
      "description": "White painted panel door with chrome handle",
      "condition":   "In good order",
      "sectionId":   "abc123",
      "rowId":       "456"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    audio_b64    = data.get('audio')
    mime_type    = data.get('mimeType', 'audio/webm')
    item_label   = data.get('itemLabel', 'Item')
    room_name    = data.get('roomName', '')
    section_id   = data.get('sectionId')
    row_id       = data.get('rowId')
    section_type      = data.get('sectionType', 'room')  # room|condition_summary|cleaning_summary|keys|meter_readings|fire_door_safety|health_safety
    is_check_out      = bool(data.get('isCheckOut', False))
    is_damage_report  = bool(data.get('isDamageReport', False))

    if not audio_b64:
        return jsonify({'error': 'No audio data'}), 400

    # Debug: log what we received
    print(f'[transcribe/item] mimeType received: {repr(mime_type)}')
    print(f'[transcribe/item] audio_b64 length: {len(audio_b64)}')

    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'error': 'OPENAI_API_KEY not configured on server'}), 503

    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        return jsonify({'error': 'Invalid base64 audio data'}), 400

    try:
        raw_transcript, audio_secs = _whisper_transcribe(audio_bytes, mime_type)

        if not raw_transcript:
            return jsonify({'error': 'No speech detected in recording'}), 422

        # Detect edit-mode trigger phrases before passing to Claude
        edit_mode, edit_field, transcript = _detect_edit_mode(raw_transcript)

        # Check Out inspections do not support delete or add-sub commands.
        # "Not seen" at check-out means the item was there at check-in but is now missing —
        # it is meaningful condition content, not a deletion trigger.
        # Items must never be deleted from a check-out report.
        if is_check_out and edit_mode in ('delete', 'add_sub'):
            edit_mode = 'normal'
            edit_field = None
            transcript = raw_transcript

        print(f'[transcribe/item] edit_mode={edit_mode!r} field={edit_field!r} transcript={transcript[:60]!r}')

        # ── Delete: "Not Applicable" — no Claude call needed ──────────────
        if edit_mode == 'delete':
            return jsonify({
                'transcript': raw_transcript,
                'editMode':   'delete',
                'editField':  None,
                'sectionId':  section_id,
                'rowId':      row_id,
                'sectionType': section_type,
            })

        filled, filled_msg = _claude_fill_item(transcript, item_label, room_name, section_type, edit_mode, is_check_out, is_damage_report)

        # Log usage
        try:
            usage = TranscriptionUsage(
                call_type     = 'item',
                inspection_id = int(data.get('inspectionId')) if data.get('inspectionId') else None,
                user_id       = int(get_jwt_identity()),
                audio_seconds = audio_secs,
                input_tokens  = filled_msg.usage.input_tokens  if filled_msg and filled_msg.usage else 0,
                output_tokens = filled_msg.usage.output_tokens if filled_msg and filled_msg.usage else 0,
                section_type  = section_type,
            )
            db.session.add(usage)
            db.session.commit()
        except Exception:
            pass  # never let logging break the response

        return jsonify({
            'transcript':       raw_transcript,   # return original for reference
            'description':      filled.get('description', ''),
            'condition':        filled.get('condition', ''),
            'notes':            filled.get('notes', ''),
            'cleanlinessNotes': filled.get('cleanlinessNotes', ''),
            'locationSerial':   filled.get('locationSerial', ''),
            'reading':          filled.get('reading', ''),
            '_subs':            filled.get('_subs', []),   # populated when "Add sub item" used
            'sectionId':        section_id,
            'rowId':            row_id,
            'sectionType':      section_type,
            'editMode':         edit_mode,    # 'normal' | 'overwrite' | 'append' | 'add_sub'
            'editField':        edit_field,   # 'description' | 'condition' | None
        })

    except Exception as e:
        import traceback
        print(f'[transcribe/item] Error: {e}')
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@transcribe_bp.route('/classify-photo', methods=['POST'])
@jwt_required()
def classify_photo():
    """
    Accepts a base64 image and room/item context string.
    Uses Claude vision to identify which room and item the photo belongs to.

    Request JSON:
    {
      "imageBase64": "<base64 jpeg>",
      "mimeType":    "image/jpeg",
      "roomContext": "<formatted room+item list string>"
    }

    Response JSON:
    {
      "sectionKey":  "42",
      "sectionName": "Bedroom 1",
      "itemKey":     "87",
      "itemName":    "Door & Frame",
      "confidence":  0.92
    }
    """
    data = request.get_json(force=True)
    image_base64  = data.get('imageBase64', '')
    mime_type     = data.get('mimeType', 'image/jpeg')
    room_context  = data.get('roomContext', '')
    inspection_id = int(data.get('inspectionId')) if data.get('inspectionId') else None

    if not image_base64 or not room_context:
        return jsonify({'error': 'imageBase64 and roomContext are required'}), 400

    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    prompt = f"""You are a property inspection assistant. Look at this photo carefully and identify which item in the room it belongs to.

{room_context}

Each item above may include a "described as" note (what the inspector has already written about it) and/or a "condition" note. Use these text descriptions alongside your visual analysis — if an item's description matches what you see in the photo, that is a strong signal.

Common property inspection items and what they look like:
- Door Fittings / Door & Frame: door handles, hinges, door frames, locks, letterboxes, door furniture
- Lighting / Light Fitting: ceiling lights, pendant lights, light shades, lampshades, wall lights, spotlights, bulbs, light fittings
- Walls: painted surfaces, wallpaper, plasterwork, wall damage, marks, dado rails
- Ceiling: ceiling surfaces, coving, cornices, ceiling roses
- Floor / Flooring: carpet, hardwood, laminate, tiles, vinyl, skirting boards
- Windows / Window & Frame: glass panes, window frames, window sills, blinds, curtains, curtain rails
- Radiator / Heating: radiators, heating units, thermostats, towel rails
- Sockets & Switches: electrical outlets, light switches, fuse boxes, consumer units
- Smoke Alarm / Carbon Monoxide Alarm: round alarm units mounted on ceiling or wall
- Kitchen appliances: oven, hob, microwave, dishwasher, fridge, extractor fan
- Bathroom: bath, shower, sink, toilet, taps, shower screen, tiles

Respond ONLY with a raw JSON object — no markdown, no backticks, no explanation, just the JSON:
{{"sectionKey":"<key>","sectionName":"<room name>","itemKey":"<key>","itemName":"<item name>","confidence":0.92}}

Rules:
- confidence is a number from 0.0 to 1.0
- Give confidence above 0.8 only when you are certain of both the room AND the item
- If an item's existing description closely matches what you see visually, increase your confidence accordingly
- If you can identify the item type but are unsure which one in the list, give 0.5-0.7
- sectionKey and itemKey must be copied exactly from the provided context list
- Match to the single closest item in the list"""

    try:
        message = client.messages.create(
            model='claude-opus-4-5',
            max_tokens=150,
            messages=[{
                'role': 'user',
                'content': [
                    {
                        'type': 'image',
                        'source': {
                            'type':       'base64',
                            'media_type': mime_type,
                            'data':       image_base64,
                        },
                    },
                    {
                        'type': 'text',
                        'text': prompt,
                    },
                ],
            }],
        )

        raw = message.content[0].text.strip()
        raw = raw.replace('```json', '').replace('```', '').strip()
        result = json.loads(_sanitise_json(raw))

        # Ensure all required fields are present
        for field in ('sectionKey', 'sectionName', 'itemKey', 'itemName'):
            if field not in result:
                result[field] = ''
        result['confidence'] = float(result.get('confidence', 0))

        # Log usage
        try:
            usage_log = TranscriptionUsage(
                call_type     = 'photo',
                inspection_id = inspection_id,
                user_id       = int(get_jwt_identity()),
                audio_seconds = 0,
                input_tokens  = message.usage.input_tokens  if message.usage else 0,
                output_tokens = message.usage.output_tokens if message.usage else 0,
                section_type  = 'photo',
            )
            db.session.add(usage_log)
            db.session.commit()
        except Exception:
            pass  # never let logging break the response

        return jsonify(result)

    except json.JSONDecodeError as e:
        # Claude returned something that wasn't valid JSON — return gracefully
        print(f'[classify-photo] JSON parse error: {e}, raw: {raw!r}')
        return jsonify({
            'sectionKey': '', 'sectionName': '',
            'itemKey': '',    'itemName': '',
            'confidence': 0,
        })

    except Exception as e:
        import traceback
        print(f'[classify-photo] Error: {e}')
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@transcribe_bp.route('/usage', methods=['GET'])
@jwt_required()
def transcribe_usage():
    """Returns usage stats and cost estimates in GBP, grouped by inspection."""
    from datetime import datetime, timedelta, timezone
    from models import Inspection

    period = request.args.get('period', '30')
    since  = datetime.now(timezone.utc) - timedelta(days=int(period))
    rows   = TranscriptionUsage.query.filter(TranscriptionUsage.created_at >= since).all()

    # ── Pricing constants ──────────────────────────────────────────────────
    USD_TO_GBP            = 0.79
    WHISPER_PER_MIN_USD   = 0.006          # Whisper-1 ($0.006/min)
    HAIKU_IN_PER_1M_USD   = 0.80           # claude-haiku-4-5 input
    HAIKU_OUT_PER_1M_USD  = 4.00           # claude-haiku-4-5 output
    # Photo classification uses claude-opus-4-5 — apply Opus-tier pricing
    OPUS_IN_PER_1M_USD    = 15.00          # claude-opus-4-5 input
    OPUS_OUT_PER_1M_USD   = 75.00          # claude-opus-4-5 output

    def _row_cost_usd(r):
        """Compute USD cost for a single usage row using the correct model pricing."""
        if r.call_type == 'photo':
            # Vision + Opus pricing
            return (r.input_tokens  / 1_000_000) * OPUS_IN_PER_1M_USD  + \
                   (r.output_tokens / 1_000_000) * OPUS_OUT_PER_1M_USD
        else:
            # Whisper + Haiku pricing (item / room / full)
            whisper = (r.audio_seconds / 60) * WHISPER_PER_MIN_USD
            claude  = (r.input_tokens  / 1_000_000) * HAIKU_IN_PER_1M_USD + \
                      (r.output_tokens / 1_000_000) * HAIKU_OUT_PER_1M_USD
            return whisper + claude

    # ── Overall summary ────────────────────────────────────────────────────
    item_count  = sum(1 for r in rows if r.call_type == 'item')
    room_count  = sum(1 for r in rows if r.call_type == 'room')
    full_count  = sum(1 for r in rows if r.call_type == 'full')
    photo_count = sum(1 for r in rows if r.call_type == 'photo')

    trans_rows = [r for r in rows if r.call_type in ('item', 'room', 'full')]
    photo_rows = [r for r in rows if r.call_type == 'photo']

    total_audio_secs = sum(r.audio_seconds for r in trans_rows)

    whisper_usd     = sum((r.audio_seconds / 60) * WHISPER_PER_MIN_USD for r in trans_rows)
    haiku_usd       = sum((r.input_tokens / 1_000_000) * HAIKU_IN_PER_1M_USD +
                          (r.output_tokens / 1_000_000) * HAIKU_OUT_PER_1M_USD
                          for r in trans_rows)
    photo_opus_usd  = sum((r.input_tokens / 1_000_000) * OPUS_IN_PER_1M_USD +
                          (r.output_tokens / 1_000_000) * OPUS_OUT_PER_1M_USD
                          for r in photo_rows)
    total_usd = whisper_usd + haiku_usd + photo_opus_usd

    # ── Group by inspection ────────────────────────────────────────────────
    from collections import defaultdict
    by_insp = defaultdict(lambda: {
        'trans_seconds': 0.0,
        'trans_in': 0, 'trans_out': 0,
        'photo_in': 0, 'photo_out': 0,
        'item_calls': 0, 'room_calls': 0, 'photo_calls': 0,
        'latest_at': None,
    })

    for r in rows:
        key = r.inspection_id
        g   = by_insp[key]
        if r.call_type in ('item', 'room', 'full'):
            g['trans_seconds'] += r.audio_seconds
            g['trans_in']      += r.input_tokens
            g['trans_out']     += r.output_tokens
            if r.call_type == 'item':
                g['item_calls'] += 1
            else:
                g['room_calls'] += 1
        elif r.call_type == 'photo':
            g['photo_in']    += r.input_tokens
            g['photo_out']   += r.output_tokens
            g['photo_calls'] += 1
        if g['latest_at'] is None or r.created_at > g['latest_at']:
            g['latest_at'] = r.created_at

    # Fetch inspection details for known IDs
    known_ids = [k for k in by_insp if k is not None]
    insp_meta = {}   # id → {address, type, reference}
    if known_ids:
        insp_objs = Inspection.query.filter(Inspection.id.in_(known_ids)).all()
        for insp in insp_objs:
            addr = (insp.property.address if insp.property else None) or f'Inspection #{insp.id}'
            insp_meta[insp.id] = {
                'address':    addr,
                'type':       (insp.inspection_type or '').replace('_', ' ').title(),
                'reference':  insp.reference_number or '',
            }

    inspections_list = []
    for insp_id, g in sorted(by_insp.items(),
                              key=lambda x: x[1]['latest_at'] or datetime.min,
                              reverse=True):
        w_usd  = (g['trans_seconds'] / 60) * WHISPER_PER_MIN_USD
        hk_usd = (g['trans_in']  / 1_000_000) * HAIKU_IN_PER_1M_USD + \
                 (g['trans_out'] / 1_000_000) * HAIKU_OUT_PER_1M_USD
        op_usd = (g['photo_in']  / 1_000_000) * OPUS_IN_PER_1M_USD  + \
                 (g['photo_out'] / 1_000_000) * OPUS_OUT_PER_1M_USD

        meta = insp_meta.get(insp_id, {}) if insp_id else {}

        inspections_list.append({
            'inspection_id':          insp_id,
            'property_address':       meta.get('address', 'Unknown property') if insp_id else 'Unlinked calls',
            'inspection_type':        meta.get('type', ''),
            'reference_number':       meta.get('reference', ''),
            'total_cost_gbp':         round((w_usd + hk_usd + op_usd) * USD_TO_GBP, 4),
            'whisper_cost_gbp':       round(w_usd  * USD_TO_GBP, 4),
            'claude_cost_gbp':        round(hk_usd * USD_TO_GBP, 4),
            'photo_cost_gbp':         round(op_usd * USD_TO_GBP, 4),
            'transcription_cost_gbp': round((w_usd + hk_usd) * USD_TO_GBP, 4),
            'item_calls':             g['item_calls'],
            'room_calls':             g['room_calls'],
            'photo_calls':            g['photo_calls'],
            'audio_minutes':          round(g['trans_seconds'] / 60, 1),
            'latest_at':              g['latest_at'].isoformat() if g['latest_at'] else None,
        })

    # Sort most expensive first (secondary sort = most recent)
    inspections_list.sort(key=lambda x: x['total_cost_gbp'], reverse=True)

    return jsonify({
        'period_days':      int(period),
        'item_calls':       item_count,
        'room_calls':       room_count,
        'full_calls':       full_count,
        'photo_calls':      photo_count,
        'total_calls':      len(rows),
        'audio_minutes':    round(total_audio_secs / 60, 1),
        'whisper_cost_gbp': round(whisper_usd   * USD_TO_GBP, 4),
        'claude_cost_gbp':  round(haiku_usd     * USD_TO_GBP, 4),
        'photo_cost_gbp':   round(photo_opus_usd * USD_TO_GBP, 4),
        'total_cost_gbp':   round(total_usd     * USD_TO_GBP, 4),
        'inspections':      inspections_list,
    })


def _claude_fill_room(transcript: str, section_name: str, items: list, processed_ids: list = None) -> dict:
    """
    Fill a single room's items from a continuous dictation transcript.
    Item names are used as 'chapter headings' — the clerk says the item name
    then describes it, so the AI maps each passage to the correct item.

    items: [{ 'id': str, 'name': str, 'hasCondition': bool, 'hasDescription': bool }]
    processed_ids: item IDs already filled in a previous pass — skip unless explicitly amended.

    Returns: { itemId: { 'description': '...', 'condition': '...' } }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    items_list = '\n'.join(
        f'  {i+1}. ID: "{item["id"]}", Name: "{item["name"]}"'
        for i, item in enumerate(items)
    )

    processed_note = ''
    if processed_ids:
        id_list = ', '.join(f'"{pid}"' for pid in processed_ids)
        processed_note = f"""
══════════════════════════════════════════════════════
ALREADY-TRANSCRIBED ITEMS — skip unless explicitly amended
══════════════════════════════════════════════════════
The following item IDs were filled in a previous transcription pass and already have content:
  {id_list}

RULE: Omit these items from your output entirely UNLESS the clerk explicitly amends, adds to,
creates a sub-item on, or deletes them. If a chapter heading matches an already-transcribed
item but the content that follows is a plain description or condition (no command word) — skip it.

Include an already-transcribed item ONLY when the clerk uses one of these patterns:

  OVERWRITE — set _descAction and/or _condAction = "overwrite":
    "Amend [item name] [content]"
    "Amend [item name] description [content]"
    "Amend [item name] condition [content]"
    "[item name]. Amend. [content]"
    "[item name]. Amend description. [content]"
    "[item name]. Amend condition. [content]"
    "Return to [item name], amend, [content]"
    "Return to [item name], amend description, [content]"
    "Return to [item name], amend condition, [content]"

  APPEND — set _descAction and/or _condAction = "append":
    "Add to [item name] [content]"
    "Add to [item name] description [content]"
    "Add to [item name] condition [content]"
    "[item name]. Add. [content]"
    "[item name]. Add to description. [content]"
    "[item name]. Add to condition. [content]"
    "Return to [item name], add, [content]"
    "Return to [item name], add to description, [content]"
    "Return to [item name], add to condition, [content]"

  SUB-ITEM — output only _subs, no _descAction/_condAction:
    "[item name]. Sub-item. [description and condition]"
    "[item name]. Add sub item. [description and condition]"
    "Return to [item name], add sub item, [description and condition]"

  DELETE — output only _delete: true:
    "[item name]. Delete item."
    "[item name]. Not Applicable."
    "[item name]. Not seen."  (only when immediately after item name, not within a description)

CHAPTER-HEADING AMENDMENT PATTERN — critical rule:
When the clerk names an already-transcribed item as a CHAPTER HEADING and then IMMEDIATELY
uses an amendment or sub-item command word ("Amend", "Add", "Sub-item"), treat this as an
explicit amendment even if the item name is not repeated after the command word.
  Example: "Ceiling. Amend condition. Light scratching to left wall."
    → {{"<ceilingId>": {{"condition": "Light scratching to left wall", "_condAction": "overwrite"}}}}
  Example: "Door and frame. Add sub item. White painted frame, light scuffing."
    → {{"<doorId>": {{"_subs": [{{"description": "White painted frame", "condition": "Light scuffing"}}]}}}}
  Example: "Walls. Add to condition. Some discolouration to right wall."
    → {{"<wallsId>": {{"condition": "Some discolouration to right wall", "_condAction": "append"}}}}
"""

    prompt = f"""You are processing a UK property inventory inspection dictation for a single room.

PHASE 1 — INTERNALIZE THE TEMPLATE
Before reading the transcript, memorize the following item sequence for this room.
These are the ONLY items you will fill. They are numbered in the order the clerk is expected to cover them.

Room: {section_name}

ROOM ITEMS IN ORDER:
{items_list}

PHASE 2 — PARSE THE TRANSCRIPT
The clerk walked through the room and spoke each item name aloud followed by its description and condition.
Item names act as CHAPTER HEADINGS. When the clerk says an item name as a standalone phrase that
EXACTLY matches a name from the list above, everything that follows belongs to that item until
the next exact item name is spoken as a standalone heading.

EXACT MATCH REQUIRED FOR CHAPTER HEADINGS:
A chapter heading is ONLY when the clerk speaks the item name BY ITSELF — the item name alone,
with no preceding adjectives, no descriptive words, no prepositions, no qualifiers, nothing else.
Case-insensitive; "&" and "and" are interchangeable.

  ✓ "Flooring" alone → triggers "Flooring"
  ✓ "Built-in storage" alone → triggers "Built-In Storage"
  ✓ "Ceiling" alone → triggers "Ceiling"
  ✗ "white painted ceiling" → does NOT trigger "Ceiling" — there are words before the noun
  ✗ "light wood flooring" → does NOT trigger "Flooring" — there are words before the noun
  ✗ "frosted glass light fitting" → does NOT trigger "Lighting" — descriptive phrase
  ✗ "white painted walls" → does NOT trigger "Walls" — there are words before the noun
  ✗ "white plastic switches and sockets" → does NOT trigger any item — descriptive phrase
  ✗ "heavy scratches to flooring" → does NOT trigger "Flooring" — prepositional phrase
  ✗ "Floor" → does NOT trigger "Flooring" — different word

DO NOT ROUTE BY CONTENT SEMANTICS — this rule overrides your default understanding:
You are NOT permitted to look at what content describes and use that to decide which item it
belongs to. Your ONLY routing mechanism is an exact standalone item name announcement.

  Even if "white painted ceiling" obviously describes a ceiling surface, and even if "Ceiling"
  exists as an item in the template — if the clerk did not say "Ceiling" alone as a standalone
  announcement, the content STAYS IN THE CURRENT ITEM. Do not move it.

  Even if "frosted glass light fitting" describes a light fitting, and "Lighting" is an item —
  if no standalone "Lighting" announcement was made, the content STAYS IN THE CURRENT ITEM.

  Your semantic understanding of what words describe MUST NOT influence routing decisions.
  Only explicit standalone announcements route content.

CURRENT-ITEM LOCK — this rule overrides everything else:
Once inside an item, every word belongs to that item until an exact standalone item name is
announced. This is absolute. There are no exceptions for content that sounds like it belongs
to another item.

CRITICAL EXAMPLE — showing correct versus wrong behaviour for a real transcript:

Transcript:
"built-in storage, white painted wooden door, white painted frame, chrome handles,
white painted ceiling, frosted glass light fitting, white painted walls, white plastic
switches and sockets, white painted woodwork, light wood flooring, in good order,
light scratches to flooring, right hand side on entry"

CORRECT — everything after "built-in storage" stays in Built-in Storage:
  Built-in Storage
    Description: White painted wooden door / White painted frame / Chrome handles /
                 White painted ceiling / Frosted glass light fitting / White painted walls /
                 White plastic switches and sockets / White painted woodwork / Light wood flooring
    Condition:   In good order / Light scratches to flooring, right hand side on entry

WRONG — do NOT do this:
  Built-in Storage: door, frame, handles only
  Ceiling: white painted  ← clerk never said "Ceiling" alone
  Lighting: frosted glass light fitting  ← clerk never said "Lighting" alone
  Walls: white painted  ← clerk never said "Walls" alone
  Flooring: light wood flooring  ← clerk never said "Flooring" alone

The clerk described the interior of the Built-in Storage unit (its ceiling, light fitting, walls,
woodwork, and flooring). None of these are standalone item announcements — they are all content
of the Built-in Storage item until the clerk explicitly announces a new item name alone.
{processed_note}
Transcript:
"{transcript}"

RULES:
1. A chapter heading MUST exactly match the full item name from the numbered list above (case-insensitive;
   "&" and "and" are interchangeable). Partial words and abbreviations are NEVER chapter headings.
   Examples: "Floor" ≠ "Flooring". "Door" ≠ "Door & Frame". "Storage" ≠ "Built-In Storage".
   The clerk must say the complete item name for a heading switch to occur.
2. Extract description and condition separately. If the clerk says a single phrase, put it in description.
3. CRITICAL: Use the EXACT words the clerk spoke. Do not rephrase, paraphrase, or substitute synonyms.
   - "good order" → "Good order" (NOT "Good condition")
   - "fair wear and tear" → "Fair wear and tear"
   - "as new" or "as inventory" → preserve exactly
4. ONLY remove filler sounds (um, uh, er, errr, umm, erm) and clear false starts where the clerk immediately restarts the same phrase (e.g. "white — white painted door" → "white painted door"). Do NOT remove, shorten, or paraphrase any actual content — reproduce the clerk's words in full.
5. Only fill items that are mentioned. Omit unmentioned items entirely from the output.
6. USE UK ENGLISH SPELLING THROUGHOUT — every word in the output must use UK spelling:
   "discolouration" not "discoloration", "colour" not "color", "centre" not "center",
   "mould" not "mold", "grey" not "gray", "neighbour" not "neighbor", "recognise" not "recognize".
7. If only one piece of information is given for an item, put it in description.

FORMATTING NUMBERS AND QUANTITIES:
- Convert spoken numbers to numerals: "two" → "2", "three" → "3"
- Format quantities as "N x item": "two green curtains" → "2 x green curtains"
- Capitalise the first word of each line
- Do NOT use bullet points or dashes
- MULTI-COMPONENT LINES — CRITICAL: when a description or condition contains more than one distinct
  component or observation, separate each with a newline character \n — NEVER use commas to join them.
  ✓ CORRECT:   "White painted door\nChrome lever handle\nChrome letter box"
  ✗ INCORRECT: "White painted door, chrome lever handle, chrome letter box"
  ✓ CORRECT:   "In good order\nLight scuffing to base\nLight wear to corners"
  ✗ INCORRECT: "In good order, light scuffing to base, light wear to corners"
  This applies to BOTH description AND condition fields without exception.
  Commas are only acceptable within a single observation (e.g. "Light scuff to base of door, left side").

APPLIANCE FORMATTING — for any appliance (washing machine, dishwasher, fridge, oven, hob, dryer, microwave, etc.):
- Each attribute MUST be on its own line — NEVER merge them into a single line
- Order: appliance type, then colour and brand, then model number, then serial number
  ✓ CORRECT:   "Washing machine\nWhite Indesit\nModel number: WD1234\nSerial number: AB5678"
  ✗ INCORRECT: "White Indesit washing machine, model number WD1234, serial number AB5678"
- Format spoken model/serial references as "Model number: X" and "Serial number: X"

SPLITTING description vs condition:
- Condition signal phrases: "in good order", "in fair order", "in poor order", "good order",
  "fair order", "poor order", "as new", "as inventory", "in good condition"
- Everything said AFTER a condition phrase is also condition
- Functional observations ("appear complete", "tested", "appears working") are always condition
- If no condition is mentioned, default condition to "In good order"
- DESCRIPTION CLOSES PERMANENTLY the moment a condition signal phrase (or defect phrase) is
  encountered. Once closed, NO further text may be added to description — not even text that
  sounds descriptive. All remaining text for that element goes into condition only.
  The only exception is an explicit amendment command from the clerk.

HOW TO PARSE EACH ITEM — follow this algorithm exactly:

STEP 1: When the clerk says an item name (CHAPTER HEADING), start collecting for that item.
STEP 2: Collect words as DESCRIPTION for the current element, until you hit a CONDITION SIGNAL PHRASE.
STEP 3: When you hit a CONDITION SIGNAL PHRASE, it IMMEDIATELY and PERMANENTLY closes the description.
         The description field is now LOCKED — no further text may be written to it for this element
         under any circumstances (unless the clerk explicitly uses an amendment command).
         The condition signal PLUS any location qualifiers that follow ("to [place]", "at [place]",
         "near [place]", "throughout", "on [place]") = the CONDITION for the current element.
         Keep collecting into the condition until you reach a new DESCRIPTIVE TERM or the next chapter heading.
STEP 4: After a condition closes, if the next word is a DESCRIPTIVE TERM (material, colour, surface, quantity),
         it starts a NEW ELEMENT → a "_subs" entry with its own description and condition.
         → Go back to STEP 2 for the new element.
STEP 5: Repeat for as many elements as the clerk describes.

The first element = the main item fields ("description" + "condition").
Each additional element = a "_subs" entry.

CONDITION SIGNAL PHRASES — these close the current element's description:
  State phrases:  "in good order", "in fair order", "in poor order", "good order", "fair order",
                  "poor order", "as new", "as inventory", "in good condition", "in fair condition",
                  "in poor condition", "in clean condition"
  Defect phrases: "light scuffing", "light scratching", "light marking", "light staining",
                  "chipped", "cracked", "stained", "marked", "damaged", "worn", "faded",
                  "scratched", "some wear", "fair wear and tear",
                  "loose", "slightly loose", "tight", "stiff", "sticky", "missing",
                  "broken", "rattling", "squeaking", "bent", "rusted", "corroded",
                  "scuff to", "chip to", "crack to", "stain to", "mark to", "scratch to"

══════════════════════════════════════════════════════
CRITICAL LOCATION QUALIFIER RULE — read this carefully
══════════════════════════════════════════════════════
The words "to [location]", "at [location]", "near [location]", or "on [location]" that
IMMEDIATELY FOLLOW a defect/state phrase are PART OF THE CONDITION.
They tell you WHERE the defect is. They are NEVER the start of a new element.

  ✓ CORRECT: "light scuffing to right hand side wall"
      → condition: "Light scuffing to right hand side wall"
      → "right hand side wall" is the scuffing's location — NOT a new sub-item description.

  ✓ CORRECT: "chip to base of door"
      → condition: "Chip to base of door"

  ✓ CORRECT: "marked to left hand wall"
      → condition: "Marked to left hand wall"

A new element ONLY starts when a NEW DESCRIPTIVE TERM appears (material, colour, surface,
quantity) AFTER the condition has fully closed.

══════════════════════════════════════════════════════
STRICT CHAPTER HEADING RULE — prevents content bleeding between items
══════════════════════════════════════════════════════
A chapter heading switch can ONLY occur when ALL of the following are true:
  1. The previous item's content (description AND condition) has fully closed.
  2. The item name is the VERY FIRST word(s) of a new utterance — nothing spoken before it
     in the same clause, phrase, or breath group.
  3. The spoken phrase EXACTLY matches the full item name from the list (case-insensitive;
     "&" ↔ "and"). Partial words and abbreviations do not qualify.

Words matching another item's name that appear WITHIN an item's description or condition
are NEVER a chapter heading switch — they are content for the CURRENT item only.

  ✓ CORRECT: "Built-in storage. White painted door and frame, in good order."
      → Entirely Built-in storage. "door and frame" is part of the storage description.
        It does NOT switch to the "Door & Frame" item.

  ✓ CORRECT: "Built-in storage. White shelving unit, floor-level drawer, in good order."
      → Entirely Built-in storage. "floor-level" is NOT a heading for Flooring.
        "floor" appears mid-sentence as part of a description — it stays with Built-in storage.

  ✓ CORRECT: "Built-in storage. White painted walls to interior, in good order."
      → Entirely Built-in storage. "walls" here refers to the interior surfaces of the
        storage unit, not the room's Walls item.

  ✗ WRONG: switching to "Flooring" because "floor" appears in "floor-level shelf" inside
      a Built-in Storage passage — this is content bleeding and must never happen.

  ✗ WRONG: treating "door and frame" inside a Built-in Storage passage as a heading for
      the separate "Door & Frame" item — this is content bleeding.

  ✓ CORRECT: "Built-in storage. White painted door and frame, in good order.
              Door and frame. White painted timber door. In good order."
      → The second "Door and frame" opens a CLEARLY ISOLATED new passage after Built-in
        storage's condition has closed — this correctly switches to the Door & Frame item.

The definitive test: does the item name appear as the FIRST WORD(S) after a condition
has fully closed? If yes → chapter heading. If it appears after other words in a running
sentence → it is content, never a heading.

══════════════════════════════════════════════════════
DELETE ITEM — remove command
══════════════════════════════════════════════════════
The clerk may say "[item name] Delete Item", "[item name] Not Applicable", or
"[item name] Not seen" to mark an item as not present in the property.
When you detect any of these commands:
  - Set "_delete": true on that item's output
  - Do NOT fill description or condition — omit them

CRITICAL CONTEXT RULE FOR "not seen":
"Not seen" is a delete command ONLY when it appears IMMEDIATELY after an item title with
no intervening description. If it appears inside a longer passage about the item, it is
descriptive content (e.g. referring to a serial number that could not be read) and must
NOT trigger deletion.

  ✓ DELETE: "Windows & Frames. Not seen."
      → {{"<windowsId>": {{"_delete": true}}}}
  ✗ NOT DELETE: "BOSCH black glass hob, model and serial number not seen."
      → dictate normally; "not seen" refers to the serial number, not the item

Examples:
  "Built-in Storage. Delete Item."
  → {{"<builtInStorageId>": {{"_delete": true}}}}
  "Fireplace. Not Applicable."
  → {{"<fireplaceId>": {{"_delete": true}}}}
  "Windows & Frames. Not seen."
  → {{"<windowsId>": {{"_delete": true}}}}

══════════════════════════════════════════════════════
EXPLICIT SUB-ITEM TRIGGER — highest priority rule
══════════════════════════════════════════════════════
The clerk may use ANY of the following phrases to EXPLICITLY signal a new sub-item:
  "sub-item", "sub item", "next sub-item", "next sub item",
  "add sub item", "add sub-item", "add a sub item", "add a sub-item"
When you encounter any variation of these phrases:
  - Immediately close the current element (its description + condition are complete)
  - Begin collecting a fresh description and condition for the next _subs entry
  - Do NOT treat the trigger phrase itself as part of any description or item name

The "Add sub item" command may appear at any point in the dictation — including at the start
of a new recording clip — to add a sub-item to the most recently described room item.
It may also appear AFTER a fully described item (description + condition already given),
in which case what follows is the new sub-item's content.

Example — two-wall room with explicit trigger:
  "Walls. White emulsion. In good order. Sub-item. Light scuffing to base of wall."
  → main:   description="White emulsion"  condition="In good order"
  → sub[0]: description=""               condition="Light scuffing to base of wall"

Example — door and frame with "Add sub item":
  "Door and frame. White UPVC door, chrome handle. In good order. Add sub item.
   White painted frame, chrome hinges. Light scuffing to base."
  → main:   description="White UPVC door\nChrome handle"     condition="In good order"
  → sub[0]: description="White painted frame\nChrome hinges" condition="Light scuffing to base"

Example — three elements with two triggers:
  "Walls. White emulsion. In good order. Sub-item. White emulsion. Light scuffing to base.
   Sub-item. White emulsion. Fair wear and tear."
  → main:   description="White emulsion"  condition="In good order"
  → sub[0]: description="White emulsion"  condition="Light scuffing to base"
  → sub[1]: description="White emulsion"  condition="Fair wear and tear"

When no explicit trigger is used, fall back to the automatic detection rules below.

══════════════════════════════════════════════════════
THE GOLDEN RULE — what triggers a new sub-item (automatic detection)
══════════════════════════════════════════════════════
A new sub-item is created ONLY when, after a condition closes, the clerk begins describing
a DIFFERENT surface or component with its own descriptive words.

  ✓ Creates sub-item: "Green painted [condition closes] … White painted …"
      (new colour = new element)
  ✓ Creates sub-item: "White UPVC door, in good order … White painted frame, light scuffing"
      (new component = new element)
  ✗ Does NOT create sub-item: "light scuffing to right hand side wall"
      ("right hand side wall" is a location qualifier, not a new component)

MULTI-COMPONENT (no sub-item): When the clerk lists several parts of the SAME thing and
  gives ONE condition phrase at the end covering everything:
  "White painted door, white painted frame, chrome lever handle … in good order"
  → description: "White painted door\nWhite painted frame\nChrome lever handle"
    condition:   "In good order"
  This is NOT a sub-item — everything shares one condition phrase.

WORKED EXAMPLES:

EXAMPLE 1 — Two walls, each with its own condition → main + 1 sub-item:
  Transcript: "Walls. Green painted, in good order. White painted, light scuffing to right hand side wall."
  Parsing:
    "green painted" → description of element 1
    "in good order" → condition signal → closes element 1 description → condition: "In good order"
    "white painted" → new descriptive term → starts element 2 (sub-item)
    "light scuffing to right hand side wall" → condition of element 2
       ("right hand side wall" = location of scuffing, stays in condition)
  → main:   description="Green painted"   condition="In good order"
  → sub[0]: description="White painted"   condition="Light scuffing to right hand side wall"
  ✗ WRONG would be: merging "green painted" + "white painted" into one description
  ✗ WRONG would be: making "right hand side wall" a sub-item description

EXAMPLE 2 — Door and frame with different conditions → main + 1 sub-item:
  "Door and frame. White UPVC door, chrome lever handle … in good order.
   White painted timber frame, chrome hinges … light scuffing to base."
  → main:   description="White UPVC door\nChrome lever handle"           condition="In good order"
  → sub[0]: description="White painted timber frame\nChrome hinges"      condition="Light scuffing to base"

EXAMPLE 3 — Three elements → main + 2 sub-items:
  "Window and frame. White UPVC frame, chrome handle … in good order.
   White net curtain … in good order.
   White roller blind … one slat cracked."
  → main:   description="White UPVC frame\nChrome handle"  condition="In good order"
  → sub[0]: description="White net curtain"                condition="In good order"
  → sub[1]: description="White roller blind"               condition="One slat cracked"

EXAMPLE 4 — Multiple components, ONE shared condition → NOT a sub-item:
  "Ceiling. White emulsion, coving to perimeter … in good order."
  → description="White emulsion\nCoving to perimeter"  condition="In good order"
  (No text after the condition → no sub-item needed.)

EXAMPLE 5 — Defect with location qualifier → ONE element, no sub-item:
  "Walls. White emulsion. Light scuffing to base of wall throughout."
  → description="White emulsion"   condition="Light scuffing to base of wall throughout"
  ("to base of wall throughout" qualifies the location → all stays in condition)

══════════════════════════════════════════════════════
AMENDMENT RULES — correcting or extending a previously-filled item
══════════════════════════════════════════════════════
The clerk may amend or extend an already-described item using these commands:

  PRIMARY FORMAT (preferred):
  "Amend [item name] description [new content]"   → overwrite description only
  "Amend [item name] condition [new content]"     → overwrite condition only
  "Add to [item name] description [new content]"  → append to description only
  "Add to [item name] condition [new content]"    → append to condition only

  LEGACY FORMAT (also accepted):
  "Return to [item name], amend description, [new text]"
  "Return to [item name], amend condition, [new text]"
  "Return to [item name], add to description, [new text]"
  "Return to [item name], add to condition, [new text]"
  "Return to [item name], amend, [new text]"  — overwrite both fields
  "Return to [item name], add, [new text]"    — append to both fields
  "Return to [item name], add sub item [description and condition]"   (also accepted: "add sub-item")
      → creates a new _subs entry on the named item; parse description/condition using the
         same sub-item rules. Do NOT include _descAction or _condAction — only output _subs.
      → For the sub-item content, split description from condition using the same condition
         signal phrases listed above — including defect words such as "loose", "broken",
         "missing", "stiff", "tight" etc. which are always condition, not description.

  Example: "Return to Contents, add sub item, chrome doorstop, slightly loose."
    → Locate the item named "Contents" and append a sub-item:
       _subs: [{{"description": "Chrome doorstop", "condition": "Slightly loose"}}]
    ("slightly loose" is a defect observation → condition, not description)

When you detect any amendment phrase, include these optional action flags in that item's JSON:
  "_descAction": "overwrite"  → caller will replace the existing description
  "_descAction": "append"     → caller will append this to the existing description
  "_condAction": "overwrite"  → caller will replace the existing condition
  "_condAction": "append"     → caller will append this to the existing condition

If no amendment phrase — omit the action flags entirely (default behaviour = fill only if empty).
"Amend [item]" with no field specified → set BOTH _descAction and _condAction to "overwrite".
"Add to [item]" with no field specified → set BOTH _descAction and _condAction to "append".

{_CONDITION_WORDS}
{_DESCRIPTION_VOCABULARY}

Return ONLY valid JSON — no markdown, no extra text.
Items without sub-items use the flat shape. Items WITH sub-items include the "_subs" array.
Amendment flags are optional — only include when the clerk explicitly amends/adds.
The "_delete" flag is only included when the clerk says "Delete Item" or "Not Applicable" for that item.
{{
  "<itemId>": {{
    "description": "...",
    "condition": "..."
  }},
  "<deletedItemId>": {{
    "_delete": true
  }},
  "<amendedItemId>": {{
    "description": "replacement or addition text",
    "condition": "replacement or addition text",
    "_descAction": "overwrite",
    "_condAction": "append"
  }},
  "<itemIdWithSubs>": {{
    "description": "first element description",
    "condition": "first element condition",
    "_subs": [
      {{ "description": "second element description", "condition": "second element condition" }},
      {{ "description": "third element description", "condition": "third element condition" }}
    ]
  }}
}}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=4000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    try:
        return json.loads(_sanitise_json(raw)), message
    except json.JSONDecodeError:
        print(f'[_claude_fill_room] JSON parse error: {raw[:200]}')
        return {}, message


def _claude_fill_room_checkout(transcript: str, section_name: str, items: list) -> dict:
    """
    Check-out version of _claude_fill_room.
    Items may include existing sub-items (with _sid + description) for routing.
    The clerk names an item (or sub-item) then states the check-out condition verbatim.

    Returns: { itemId: { "checkOutCondition": "..." } }
          or { itemId: { "_subs": [{ "_sid": "...", "checkOutCondition": "..." }] } }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    # Build items list with sub-items for the prompt
    lines = []
    for item in items:
        lines.append(f'  - ID: "{item["id"]}", Name: "{item["name"]}"')
        subs = item.get('subs', [])
        for sub in subs:
            desc = (sub.get('description') or '').strip()
            if desc:
                lines.append(f'    Sub-item: _sid="{sub["_sid"]}", Description: "{desc}"')
    items_list = '\n'.join(lines)

    prompt = f"""You are processing a UK property CHECK-OUT inspection dictation for a single room.

The clerk walks through the room describing each item's condition at the END of the tenancy.
Item names act as CHAPTER HEADINGS — everything said after an item name fills that item's check-out condition.
If an item has sub-items listed below it (indented), the clerk may name a sub-item by its description to target it specifically.

Room: {section_name}

Items to fill (sub-items are indented below their parent):
{items_list}

Transcript:
"{transcript}"

VERBATIM RULES — absolute, no exceptions:
1. Use the EXACT words the clerk spoke for check-out conditions. Do NOT interpret, condense, or paraphrase.
   - "2 x bulbs expired" → "2 x bulbs expired"  (NOT just "expired")
   - ONLY remove filler sounds: um, uh, er, errr, umm, erm
   - Clear false starts only (e.g. "white — white door" → "white door")
2. Convert spoken numbers to numerals: "two" → "2", "three" → "3"
3. Format quantities as "N x item": "two bulbs" → "2 x bulbs"
4. If the clerk names an item directly: fill its "checkOutCondition" field.
5. If the clerk names a sub-item (matching its Description): fill that sub-item's "checkOutCondition"
   and include it under the parent item's "_subs" array, using the exact _sid shown above.
6. Capitalise the first word of each observation.
7. Only fill items/sub-items that are mentioned. Omit everything else.
8. USE UK ENGLISH SPELLING — "discolouration" not "discoloration", "colour" not "color",
   "mould" not "mold", "grey" not "gray", "centre" not "center".
9. SEPARATE OBSERVATIONS ON DIFFERENT LINES: if the clerk mentions two or more distinct observations
   about different parts or fittings of the same item, put each on its own line using \\n.
   NEVER join separate observations with a comma — use \\n instead.
   Example: "handles slightly loose, one screw missing to interior handle"
     CORRECT:   "Handles slightly loose\\nOne screw missing to interior handle"
     INCORRECT: "Handles slightly loose, one screw missing to interior handle"
   A single observation about one thing may still use commas within that one line.

Return ONLY valid JSON — no markdown, no extra text.
Use "checkOutCondition" (not "condition") for all fields.
Example output:
{{
  "<itemId>": {{
    "checkOutCondition": "clerk's exact words"
  }},
  "<itemIdWithSubs>": {{
    "_subs": [
      {{ "_sid": "exact_sid_from_above", "checkOutCondition": "clerk's exact words" }}
    ]
  }}
}}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=2000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    try:
        return json.loads(_sanitise_json(raw)), message
    except json.JSONDecodeError:
        print(f'[_claude_fill_room_checkout] JSON parse error: {raw[:200]}')
        return {}, message


def _claude_fill_room_damage(transcript: str, section_name: str, items: list, processed_ids: list = None) -> dict:
    """
    Damage Report version of _claude_fill_room.
    Item names act as chapter headings; everything the clerk says maps to 'condition' only.
    No description field is ever populated.

    Returns: { itemId: { 'condition': '...' } }
          or { itemId: { '_subs': [{ 'condition': '...' }] } }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    items_list = '\n'.join(
        f'  - ID: "{item["id"]}", Name: "{item["name"]}"'
        for item in items
    )

    processed_note = ''
    if processed_ids:
        id_list = ', '.join(f'"{pid}"' for pid in processed_ids)
        processed_note = f"""
══════════════════════════════════════════════════════
ALREADY-TRANSCRIBED ITEMS — skip unless explicitly amended
══════════════════════════════════════════════════════
The following item IDs were filled in a previous pass and already have condition content:
  {id_list}

Omit these items entirely UNLESS the clerk explicitly amends, adds to, creates a sub-item on,
or deletes them. Accepted patterns:

  OVERWRITE (_condAction = "overwrite"):
    "Amend [item name] condition [content]" | "[item name]. Amend condition. [content]"
    "Return to [item name], amend condition, [content]"

  APPEND (_condAction = "append"):
    "Add to [item name] condition [content]" | "[item name]. Add to condition. [content]"
    "Return to [item name], add to condition, [content]"

  SUB-ITEM (output only _subs):
    "[item name]. Sub-item. [damage]" | "Return to [item name], add sub-item, [damage]"

  DELETE (_delete: true):
    "[item name]. Delete item." | "[item name]. Not Applicable." | "[item name]. Not seen."
    ("Not seen" only deletes when IMMEDIATELY after the item name — not when inside a description)

CHAPTER-HEADING PATTERN: If the clerk names an already-transcribed item as a chapter heading
and IMMEDIATELY follows with a command word ("Amend", "Add", "Sub-item"), treat it as explicit.
  Example: "Door and frame. Amend condition. Chip to base."
    → {{"<doorId>": {{"condition": "Chip to base", "_condAction": "overwrite"}}}}
"""

    prompt = f"""You are processing a UK property DAMAGE REPORT inspection dictation for a single room.

The clerk walks through the room and says each item name followed by a description of the damage.
Item names act as CHAPTER HEADINGS — everything said after an item name goes into that item's
"condition" field. There is NO description field in a damage report.

Room: {section_name}

Items (use the ID as the JSON key, match by Name):
{items_list}
{processed_note}
Transcript:
"{transcript}"

RULES:
1. A chapter heading MUST exactly match the full item name from the list above (case-insensitive;
   "&" and "and" are interchangeable). Partial words and abbreviations are NEVER chapter headings.
   Examples: "Floor" ≠ "Flooring". "Door" ≠ "Door & Frame". "Storage" ≠ "Built-In Storage".
   The clerk must say the complete item name for a heading switch to occur.
2. Everything the clerk says after an item name is DAMAGE CONDITION — put it all in "condition".
   Never use a "description" field.
3. VERBATIM: use the clerk's exact words. Only remove filler sounds (um, uh, er, errr, umm, erm)
   and clear false starts (e.g. "scuff — scuff to base" → "scuff to base").
4. MULTIPLE OBSERVATIONS: when the clerk mentions two or more distinct damage observations,
   separate each with a newline (\\n). NEVER use commas to join separate observations.
   ✓ CORRECT:   "Scuff to bottom panel\\nChip to frame"
   ✗ INCORRECT: "Scuff to bottom panel, chip to frame"
   A single observation about one location may still use commas within that line.
5. Convert spoken numbers to numerals: "two" → "2". Format quantities as "N x item".
6. Capitalise the first word of each line.
7. Only fill items that are mentioned. Omit unmentioned items entirely.
8. If a single component has multiple distinct damage observations, each goes on its own line.
9. USE UK ENGLISH SPELLING — "discolouration" not "discoloration", "colour" not "color",
   "mould" not "mold", "grey" not "gray", "centre" not "center".

══════════════════════════════════════════════════════
DELETE ITEM
══════════════════════════════════════════════════════
The clerk may say "[item name] Delete Item", "[item name] Not Applicable", or
"[item name] Not seen" to mark an item as not present.
  → Set "_delete": true on that item. Do NOT fill condition.

CRITICAL CONTEXT RULE FOR "not seen":
"Not seen" is a delete command ONLY when it appears IMMEDIATELY after an item title with
no intervening description. If it appears inside a longer passage about the item, it is
descriptive content and must NOT trigger deletion.
  ✓ DELETE: "Windows & Frames. Not seen."  → _delete: true
  ✗ NOT DELETE: "model and serial number not seen" (within a description) → dictate normally

══════════════════════════════════════════════════════
SUB-ITEMS
══════════════════════════════════════════════════════
The clerk may use ANY of these phrases to start a new damage element within the same item:
  "sub-item", "sub item", "next sub-item", "next sub item",
  "add sub item", "add sub-item", "add a sub item"
Each sub-item has its own "condition" only. No description.

"Return to [item name], add sub-item [damage content]"
  → Creates a new _subs entry on the named item. Only condition, no _descAction/_condAction.

══════════════════════════════════════════════════════
AMENDMENT COMMANDS
══════════════════════════════════════════════════════
"Amend [item name] condition [new content]"       → overwrite condition (_condAction: "overwrite")
"Add to [item name] condition [new content]"      → append to condition (_condAction: "append")
"Return to [item name], amend condition, [text]"  → overwrite condition (_condAction: "overwrite")
"Return to [item name], add to condition, [text]" → append to condition (_condAction: "append")

Return ONLY valid JSON — no markdown, no extra text.
{{
  "<itemId>": {{
    "condition": "Damage observation one\\nDamage observation two"
  }},
  "<deletedItemId>": {{
    "_delete": true
  }},
  "<amendedItemId>": {{
    "condition": "replacement or addition",
    "_condAction": "overwrite"
  }},
  "<itemWithSubs>": {{
    "condition": "Main element damage",
    "_subs": [
      {{ "condition": "Second element damage" }},
      {{ "condition": "Third element damage" }}
    ]
  }}
}}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=3000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    try:
        return json.loads(_sanitise_json(raw)), message
    except json.JSONDecodeError:
        print(f'[_claude_fill_room_damage] JSON parse error: {raw[:200]}')
        return {}, message


def _claude_fill_fixed_section(transcript: str, section_name: str, section_type: str, items: list) -> dict:
    """
    Fill a fixed section's items from a continuous dictation transcript.
    Like _claude_fill_room but returns section-type-specific field names.

    items: [{ 'id': str, 'name': str }]

    Return shapes per section type:
      condition_summary        → { "condition": "..." }
      cleaning_summary         → { "cleanlinessNotes": "..." }
      fire_door_safety /
        health_safety /
        smoke_alarms           → { "notes": "...", "answer": "Yes"|"No"|"" }
      keys                     → { "description": "..." }
      meter_readings            → { "locationSerial": "...", "reading": "..." }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    items_list = '\n'.join(
        f'  - ID: "{item["id"]}", Name: "{item["name"]}"'
        for item in items
    )

    # Build section-specific instructions AND a concrete example output so the model
    # can follow by example rather than abstract description.
    # The \\n in field_example strings becomes a literal \n in the prompt, which is
    # exactly the JSON escape sequence needed to produce a newline in the field value.

    if section_type == 'condition_summary':
        field_instructions = (
            'Extract the condition observations into "condition". '
            'Each separate observation MUST go on its own line — use the \\n escape sequence between them. '
            'NEVER run multiple observations together as a single sentence. '
            'Use the EXACT words the clerk spoke.'
        )
        field_example = (
            '{\n'
            '  "42": {"condition": "Some wear to carpet throughout\\nScuff marks to base of walls\\nDoor handle loose"}\n'
            '}'
        )
    elif section_type == 'cleaning_summary':
        field_instructions = (
            'The clerk mentions the CATEGORY or LINE NAME first (e.g. "flooring", "kitchen surfaces"), '
            'then describes the cleanliness observation. Match the category name to the closest item, '
            'then fill "cleanlinessNotes" with the observation that follows. '
            'Each separate observation MUST go on its own line — use the \\n escape sequence between them. '
            'NEVER run multiple observations together as a single sentence. '
            'Use the EXACT words the clerk spoke.'
        )
        field_example = (
            '{\n'
            '  "55": {"cleanlinessNotes": "Grease marks to hob surface\\nLight limescale to sink taps"}\n'
            '}'
        )
    elif section_type in ('fire_door_safety', 'health_safety', 'smoke_alarms'):
        field_instructions = (
            'Extract observations into "notes". '
            'Each separate observation MUST go on its own line — use the \\n escape sequence between them. '
            'If the clerk gives a yes/no answer (e.g. "yes", "no", "working", "not working"), '
            'put "Yes" or "No" in "answer"; otherwise leave "answer" as an empty string. '
            'Use the EXACT words the clerk spoke.'
        )
        field_example = (
            '{\n'
            '  "61": {"notes": "Fitted to ceiling in hallway\\nTested and working", "answer": "Yes"}\n'
            '}'
        )
    elif section_type == 'keys':
        field_instructions = (
            'Extract key descriptions into "description". '
            'If the clerk mentions anything about collecting, receiving, handing over, or returning keys — '
            'regardless of who from or to — put this EXACTLY as spoken on the FIRST line. '
            'This line must always be included when the clerk says it '
            '(e.g. "Keys collected from and returned to Yellands Estates", "Keys handed to tenant", '
            '"Keys received from landlord"). '
            'Each key TYPE must be on its own line — use the \\n escape sequence between them. '
            'Format each key line as "N x [key type]". '
            'Convert spoken numbers to numerals ("two" → "2"). '
            'Use the EXACT words the clerk spoke.'
        )
        field_example = (
            '{\n'
            '  "70": {"description": "Keys collected from and returned to Yellands Estates\\n1 x Yale key\\n1 x Chubb key\\n2 x fob"}\n'
            '}'
        )
    elif section_type == 'meter_readings':
        field_instructions = (
            'The clerk provides explicit headings for each meter (e.g. "Gas meter", "Electricity meter", '
            '"Water meter"). Match the heading to the closest item by name. Then fill: '
            '"locationSerial" — the location on the FIRST line and serial number on the SECOND line, '
            'separated by the \\n escape sequence, formatted EXACTLY as: '
            '"Located to [location]\\nSerial Number: [number]" (omit whichever part is not mentioned); '
            '"reading" — the numeric reading value only, no units. '
            'CRITICAL: locationSerial MUST use \\n between the Located line and the Serial Number line — '
            'never put them on a single line separated by a space or comma. '
            'Use the EXACT words the clerk spoke for location and serial number descriptions.'
        )
        field_example = (
            '{\n'
            '  "81": {"locationSerial": "Located to entrance hallway storage cupboard\\nSerial Number: AB123456", "reading": "8234.5"},\n'
            '  "82": {"locationSerial": "Located to kitchen utility area\\nSerial Number: GX987654", "reading": "1045"}\n'
            '}'
        )
    else:
        field_instructions = 'Extract all observations into "notes". Use the EXACT words the clerk spoke.'
        field_example = '{\n  "<itemId>": {"notes": "Observation text here"}\n}'

    prompt = f"""You are processing a UK property inventory inspection dictation for a fixed section.

The clerk spoke each item name aloud followed by their observations.
Item names act as CHAPTER HEADINGS — everything said after an item name belongs to that item, until the next item name is spoken.

Section: {section_name}
Section type: {section_type}

Items to fill (use the ID as the JSON key, match by Name):
{items_list}

Transcript:
"{transcript}"

RULES:
1. Match each passage to the closest item name. The clerk may abbreviate — use fuzzy matching.
2. {field_instructions}
3. CRITICAL: Use the EXACT words the clerk spoke. Do not rephrase, paraphrase, or substitute synonyms.
   - "good order" → "Good order" (NOT "Good condition")
   - "fair wear and tear" → "Fair wear and tear"
4. ONLY remove filler sounds (um, uh, er, errr, umm, erm) and clear false starts where the clerk immediately restarts the same phrase. Do NOT remove, shorten, or paraphrase any actual content — reproduce the clerk's words in full.
5. Only fill items that are mentioned. Omit unmentioned items entirely from the output.
6. USE UK ENGLISH SPELLING THROUGHOUT — "discolouration" not "discoloration", "colour" not "color",
   "mould" not "mold", "grey" not "gray", "centre" not "center", "limescale" not "lime scale".
7. Capitalise the first word of each line.

LINE BREAKS — THIS IS CRITICAL:
Use the JSON escape sequence \\n (backslash + n) inside string values whenever a new line is needed.
NEVER collapse multiple pieces of information into a single run-on sentence.
Follow the example output format EXACTLY.

Example output format for this section type:
{field_example}

Return ONLY valid JSON matching that shape — no markdown, no extra text, real item IDs only."""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=3000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    try:
        return json.loads(_sanitise_json(raw)), message
    except json.JSONDecodeError:
        print(f'[_claude_fill_fixed_section] JSON parse error: {raw[:200]}')
        return {}, message


@transcribe_bp.route('/room', methods=['POST'])
@jwt_required()
def transcribe_room():
    """
    Per-room dictation — the clerk records the whole room in one go (with pause/resume),
    then presses 'AI Transcribe' in the app to fill all item fields at once.

    This replaces the old 'ai_processing' server-side flow. All processing now happens
    on demand from the app before syncing.

    Request JSON:
    {
      "clips":       [{"audio": "<base64>", "mimeType": "audio/m4a"}, ...],
      "sectionName": "Living Room",
      "sectionKey":  "123",
      "items": [
        {"id": "456", "name": "Ceiling", "hasCondition": true, "hasDescription": true},
        ...
      ]
    }

    Response JSON:
    {
      "transcript": "Ceiling. Good condition, white painted...",
      "filled": {
        "456": {"description": "White painted", "condition": "In good order"}
      }
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    clips              = data.get('clips', [])
    section_name       = data.get('sectionName', 'Room')
    section_type       = data.get('sectionType', 'room')   # 'room' | fixed-section types
    items              = data.get('items', [])
    is_check_out       = bool(data.get('isCheckOut', False))
    is_damage_report   = bool(data.get('isDamageReport', False))
    processed_item_ids = data.get('processedItemIds') or []
    inspection_id      = int(data['inspectionId']) if data.get('inspectionId') else None

    if not clips:
        return jsonify({'error': 'No audio clips provided'}), 400
    if not items:
        return jsonify({'error': 'No items provided'}), 400

    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'error': 'OPENAI_API_KEY not configured on server'}), 503
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    # Transcribe each clip with Whisper, collect actual durations
    transcripts = []
    total_audio_secs = 0.0
    for i, clip in enumerate(clips):
        audio_b64 = clip.get('audio')
        mime_type = clip.get('mimeType', 'audio/m4a')
        if not audio_b64:
            continue
        try:
            audio_bytes = base64.b64decode(audio_b64)
            text, secs = _whisper_transcribe(audio_bytes, mime_type)
            if text:
                transcripts.append(text.strip())
                total_audio_secs += secs
        except Exception as e:
            print(f'[transcribe/room] clip {i} whisper error: {e}')

    full_transcript = ' '.join(transcripts)
    if not full_transcript:
        return jsonify({'error': 'No speech detected in recording'}), 422

    try:
        if section_type == 'room':
            if is_check_out:
                filled, fill_msg = _claude_fill_room_checkout(full_transcript, section_name, items)
            elif is_damage_report:
                filled, fill_msg = _claude_fill_room_damage(full_transcript, section_name, items, processed_item_ids or None)
            else:
                filled, fill_msg = _claude_fill_room(full_transcript, section_name, items, processed_item_ids or None)
        else:
            filled, fill_msg = _claude_fill_fixed_section(full_transcript, section_name, section_type, items)
    except Exception as e:
        print(f'[transcribe/room] claude error: {e}')
        return jsonify({'error': f'AI fill error: {str(e)}'}), 500

    # Log usage — previously missing for room-mode transcriptions
    try:
        usage_log = TranscriptionUsage(
            call_type     = 'room',
            inspection_id = inspection_id,
            user_id       = int(get_jwt_identity()),
            audio_seconds = total_audio_secs,
            input_tokens  = fill_msg.usage.input_tokens  if fill_msg and fill_msg.usage else 0,
            output_tokens = fill_msg.usage.output_tokens if fill_msg and fill_msg.usage else 0,
            section_type  = section_type,
        )
        db.session.add(usage_log)
        db.session.commit()
    except Exception:
        pass  # never let logging break the response

    return jsonify({
        'transcript': full_transcript,
        'filled':     filled,
    })


@transcribe_bp.route('/condition-summary', methods=['POST'])
@jwt_required()
def generate_condition_summary():
    """
    Generate a Condition Summary from the filled room inspection data.
    No audio involved — reads existing report content and synthesises notable issues.

    Request JSON:
    {
      "inspectionId": 123,
      "sections": [
        {
          "name": "Kitchen",
          "items": [
            { "name": "Ceiling", "description": "White emulsion", "condition": "In good order" },
            { "name": "Floor",   "description": "Grey vinyl",     "condition": "Worn to entrance",
              "subs": [{ "description": "Silver threshold", "condition": "Light scratching" }] }
          ]
        }
      ],
      "summaryItems": [
        { "id": "fs_2_0", "name": "General Property Condition" }
      ]
    }

    Response JSON:
    {
      "filled": {
        "fs_2_0": { "condition": "Worn vinyl flooring to Kitchen entrance\\nLight scuffing to walls in Hallway" }
      }
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    sections      = data.get('sections', [])
    summary_items = data.get('summaryItems', [])
    inspection_id = int(data['inspectionId']) if data.get('inspectionId') else None
    prop_details  = data.get('propertyDetails') or {}

    if not sections:
        return jsonify({'error': 'No inspection data provided'}), 400
    if not summary_items:
        return jsonify({'error': 'No condition summary items provided'}), 400

    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    # ── Build property description sentence ───────────────────────────────
    prop_type  = (prop_details.get('property_type') or '').strip()
    bedrooms   = prop_details.get('bedrooms')
    bathrooms  = prop_details.get('bathrooms')
    furnished  = (prop_details.get('furnished') or '').strip()
    address    = (prop_details.get('address') or '').strip()

    prop_parts = []
    if bedrooms is not None:
        prop_parts.append(f'{int(bedrooms)}-bedroom')
    if bathrooms is not None:
        prop_parts.append(f'{int(bathrooms)}-bathroom')
    if furnished:
        prop_parts.append(furnished.lower())
    if prop_type:
        prop_parts.append(prop_type.lower())

    if prop_parts:
        property_description = 'Property is a ' + ' '.join(prop_parts) + '.'
    elif address:
        property_description = f'Property at {address}.'
    else:
        property_description = 'Property details not provided.'

    # ── Format inspection findings as readable text ────────────────────────
    lines = []
    for section in sections:
        sec_name  = section.get('name', 'Room')
        sec_items = section.get('items', [])
        if not sec_items:
            continue
        sec_lines = []
        for item in sec_items:
            item_name = item.get('name', 'Item')
            desc      = (item.get('description') or '').strip()
            cond      = (item.get('condition') or '').strip()
            if not desc and not cond:
                continue
            entry = f'  - {item_name}'
            if desc:
                entry += f': {desc}'
            if cond:
                entry += f' | {cond}'
            sec_lines.append(entry)
            for sub in item.get('subs', []):
                sub_desc = (sub.get('description') or '').strip()
                sub_cond = (sub.get('condition') or '').strip()
                if sub_desc or sub_cond:
                    sub_entry = '    ↳'
                    if sub_desc:
                        sub_entry += f' {sub_desc}'
                    if sub_cond:
                        sub_entry += f' | {sub_cond}'
                    sec_lines.append(sub_entry)
        if sec_lines:
            lines.append(f'\n=== {sec_name} ===')
            lines.extend(sec_lines)

    inspection_text = '\n'.join(lines) if lines else 'No room data available.'

    items_list = '\n'.join(
        f'  {i+1}. ID: "{item["id"]}", Name: "{item["name"]}"'
        for i, item in enumerate(summary_items)
    )

    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    prompt = f"""You are writing a Condition Summary for a UK property inspection report.

════════════════════════════════════════════════════
PHASE 1 — INTERNALIZE THE SUMMARY SECTIONS
Before reading the inspection data, memorize the following sections.
Every finding must be assigned to EXACTLY ONE section. No duplication.
════════════════════════════════════════════════════

PROPERTY: {property_description}

SUMMARY SECTIONS (numbered for reference):
{items_list}

CATEGORY GUIDE — match by INSPECTION ITEM NAME (the label before the colon in the data below):
  Assign each inspection item to the summary section whose name most closely matches
  the ITEM NAME. Use the examples below as a guide for common item names:

  • Overview / Property Description  → no inspection items; use property details only
  • Decorative Order                 → items named: Decorative Order, General Condition, Paintwork
  • Doors / Frames / Fittings        → items named: Door, Door & Frame, Internal Door, Front Door, Skirting (if listed under doors)
  • Ceilings                         → items named: Ceiling, Coving
  • Lighting / Light Fittings        → items named: Lighting, Light Fitting, Light, Pendant, Spotlights
  • Walls                            → items named: Walls, Wall, Wall Surfaces
  • Windows / Fittings               → items named: Window, Window & Frame, Blind, Curtain, Curtain Track
  • Electrics / Heating              → items named: Sockets, Switches, Radiator, Boiler, Consumer Unit, Thermostat, Towel Rail
  • Woodwork / Flooring              → items named: Flooring, Floor, Carpet, Skirting Board, Architrave, Threshold, Laminate, Hard Floor
  • Contents / Furniture             → items named: Furniture, Contents, Wardrobe, Chest of Drawers, Sofa, Table, Bed,
                                        Built-in Storage, Built-in Wardrobe, Cupboard, Cabinet, Shelving, Storage
  • Appliances                       → items named: Oven, Hob, Fridge, Freezer, Washing Machine, Dishwasher, Extractor, Microwave
  • Sanitaryware / Bathrooms         → items named: Bath, Shower, Sink, Toilet, WC, Cistern, Taps, Mixer, Basin
  • Outdoor / Garden / External      → items named: Garden, Patio, Fence, Garage, Path, Driveway, Decking, Balcony

  CRITICAL — ITEM LOCK:
  An inspection item's ENTIRE condition and description stays together in ONE section.
  Do NOT read keywords inside an item's text and redistribute them to other sections.
  Example: a "Built-in Storage" item with condition "shelving worn, flooring to base damaged,
  socket inside not working" → the whole entry goes to Contents/Furniture.
  Do NOT extract "flooring" to Woodwork/Flooring or "socket" to Electrics/Heating.
  The item name, not the content text, determines the section.

════════════════════════════════════════════════════
PHASE 2 — INSPECTION FINDINGS
Draw from the following room-by-room inspection data to populate each section above.
Match each item to a section using its ITEM NAME (left of the colon), not keywords in its text.
════════════════════════════════════════════════════

{inspection_text}

════════════════════════════════════════════════════
ASSIGNMENT AND FORMATTING RULES
════════════════════════════════════════════════════

1. ONE FINDING PER LINE
   Each distinct defect or observation is a single line. Never write prose paragraphs or
   multi-sentence blocks. Never join separate issues with commas or "and".

2. ONE SECTION PER ITEM
   Each inspection item goes to exactly ONE summary section, chosen by item name.
   Do NOT repeat the same item in multiple sections.

3. GROUP BY ROOM
   Write the room name alone on its own line. List each finding for that room on the
   line(s) below. Leave one blank line between room groups.

4. SEVERITY FILTER — applies to ALL sections except Lighting, Appliances, and Overview
   INCLUDE: chips, cracks, breaks, gouges, holes, burns, damp, mould, water damage,
            missing items or fittings, non-functional items (no power, seized, jammed,
            does not operate), failed silicone/grout, heavy peeling paint, dropped hinges,
            broken locks/handles, moderate-to-major wear or damage
   EXCLUDE: anything described as "light", "slight", "minor", or "superficial";
            fair wear and tear; "in good order"; "in fair order"; "as new"; "as inventory"

5. OVERVIEW RULE
   If a section is named "Overview" or "Property Description" (or similar), write exactly
   one sentence using PROPERTY DETAILS above. No findings, no defects, no other content.
   Format: "{property_description}"
   Append outdoor features if present in the data (e.g. "with garden", "with garage").

6. LIGHTING RULE
   If a section is named "Lighting" or "Light Fittings", the first line must always be
   exactly: "All tested for power"
   Then list non-functional fittings or rooms with blown/missing bulbs only.

7. APPLIANCES RULE
   If a section is named "Appliances", the first line must always be exactly:
   "All tested for power"
   Then list appliances with no power, non-functional, or major physical damage only.

8. EMPTY SECTIONS
   If no qualifying findings exist for a section, return "In good order".
   Exception — Lighting and Appliances: return "All tested for power" (no additional text).
   Exception — Overview: return the one-sentence property summary only (no "In good order").
   NEVER write "None noted", "No issues found", or "No defects noted".

9. FORMAT
   - Capitalise the first word of each line.
   - No bullet points, dashes, or numbering on observation lines.
   - UK English: "discolouration", "colour", "grey", "mould", "centre".

════════════════════════════════════════════════════
EXAMPLE OUTPUT (Walls section with findings in two rooms)
════════════════════════════════════════════════════
Kitchen
Crack to plaster above window
Mould to corner behind boiler

Bedroom 1
Large scuff marks to wall behind door
Hole to wall, left of window

Return ONLY valid JSON — no markdown, no extra text:
{{
  "<itemId>": {{"condition": "..."}}
}}

Use \\n between lines within a condition value. Use \\n\\n between room groups.
Sections with no defects: {{"condition": "In good order"}} (or "All tested for power" for Lighting/Appliances)."""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=1500,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()

    try:
        filled = json.loads(_sanitise_json(raw))
    except json.JSONDecodeError:
        print(f'[condition-summary] JSON parse error: {raw[:200]}')
        return jsonify({'error': 'AI returned an invalid response — please try again'}), 500

    # Log usage
    try:
        usage_log = TranscriptionUsage(
            call_type     = 'item',
            inspection_id = inspection_id,
            user_id       = int(get_jwt_identity()),
            audio_seconds = 0,
            input_tokens  = message.usage.input_tokens  if message.usage else 0,
            output_tokens = message.usage.output_tokens if message.usage else 0,
            section_type  = 'condition_summary',
        )
        db.session.add(usage_log)
        db.session.commit()
    except Exception:
        pass

    return jsonify({'filled': filled})


@transcribe_bp.route('/full', methods=['POST'])
@jwt_required()
def transcribe_full():
    """
    Full inspection continuous recording — legacy endpoint, kept for backward compatibility.

    Request JSON:
    {
      "audio":    "<base64-encoded audio>",
      "mimeType": "audio/webm",
      "template": { ...simplified template structure... }
    }

    Response JSON:
    {
      "transcript": "...",
      "filled": {
        "<sectionId>": {
          "<rowId>": { "description": "...", "condition": "..." }
        }
      }
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    audio_b64 = data.get('audio')
    mime_type = data.get('mimeType', 'audio/webm')
  