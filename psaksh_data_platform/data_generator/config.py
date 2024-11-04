"""
Pakistan-wide configuration for the PSAKSH synthetic data generator.

Coverage:
  - 4 Provinces: Punjab, Sindh, KPK, Balochistan
  - 36 Districts (9 per province)
  - 5 Union Councils per district = 180 UCs
  - 3 Health facilities per district = 108 facilities (DHQ + RHC + BHU)
  - 3 Enumerators per district = 108 enumerators
  - Study period: 2022-01-01 to 2024-12-31

Data quality issues injected deliberately:
  - Bilingual English/Urdu field values (~15%)
  - Duplicate submissions (~4.5% of households)
  - Inconsistent date formats (DD/MM/YYYY, MM-DD-YYYY, etc.)
  - Out-of-range anthropometric values (~2%)
  - Missing GPS coordinates (~4%)
  - Implausible ages (~3%)
  - Typos / Urdu script in district names (~7%)
  - Blank/null notes (~90% — realistic field behaviour)
  - Enumerator ID format inconsistencies (~5%)
  - Short interview durations flagging fabrication (~5%)
"""

from __future__ import annotations
import random as _rnd

# ---------------------------------------------------------------------------
# Study design
# ---------------------------------------------------------------------------

STUDY_START_DATE = "2022-01-01"
STUDY_END_DATE   = "2024-12-31"

SES_TIERS   = ["low", "middle", "high"]
SES_WEIGHTS = [0.58, 0.32, 0.10]

# ---------------------------------------------------------------------------
# Province-level health outcome profiles (realistic Pakistan disparities)
# ---------------------------------------------------------------------------

PROVINCE_PROFILES = {
    "Punjab": {
        "stunting": 0.36, "wasting": 0.15, "underweight": 0.26,
        "anemia_child": 0.50, "anemia_mother": 0.38,
        "diarrhea_2w": 0.20, "ari_2w": 0.17, "fever_2w": 0.18,
        "exclusive_bf": 0.50, "anc_4plus": 0.60,
        "skilled_delivery": 0.78, "vaccination_full": 0.65,
    },
    "Sindh": {
        "stunting": 0.48, "wasting": 0.23, "underweight": 0.35,
        "anemia_child": 0.58, "anemia_mother": 0.46,
        "diarrhea_2w": 0.28, "ari_2w": 0.22, "fever_2w": 0.24,
        "exclusive_bf": 0.42, "anc_4plus": 0.48,
        "skilled_delivery": 0.65, "vaccination_full": 0.55,
    },
    "KPK": {
        "stunting": 0.40, "wasting": 0.17, "underweight": 0.29,
        "anemia_child": 0.52, "anemia_mother": 0.42,
        "diarrhea_2w": 0.22, "ari_2w": 0.20, "fever_2w": 0.21,
        "exclusive_bf": 0.55, "anc_4plus": 0.52,
        "skilled_delivery": 0.68, "vaccination_full": 0.60,
    },
    "Balochistan": {
        "stunting": 0.52, "wasting": 0.27, "underweight": 0.40,
        "anemia_child": 0.62, "anemia_mother": 0.52,
        "diarrhea_2w": 0.32, "ari_2w": 0.26, "fever_2w": 0.28,
        "exclusive_bf": 0.38, "anc_4plus": 0.35,
        "skilled_delivery": 0.45, "vaccination_full": 0.42,
    },
}

# National average fallback
PREVALENCE = {
    "stunting": 0.40, "wasting": 0.18, "underweight": 0.29,
    "anemia_child": 0.53, "anemia_mother": 0.42,
    "diarrhea_2w": 0.23, "ari_2w": 0.19, "fever_2w": 0.21,
    "exclusive_bf": 0.47, "anc_4plus": 0.52,
    "skilled_delivery": 0.69, "vaccination_full": 0.58,
}

# ---------------------------------------------------------------------------
# Pakistan geography — 36 districts across 4 provinces
# ---------------------------------------------------------------------------

PAKISTAN_DISTRICTS = {
    "Punjab": [
        {"name": "Lahore",           "lat": 31.5497, "lon": 74.3436, "urban": True},
        {"name": "Faisalabad",       "lat": 31.4180, "lon": 73.0790, "urban": True},
        {"name": "Multan",           "lat": 30.1575, "lon": 71.5249, "urban": True},
        {"name": "Rawalpindi",       "lat": 33.6007, "lon": 73.0679, "urban": True},
        {"name": "Gujranwala",       "lat": 32.1877, "lon": 74.1945, "urban": False},
        {"name": "Sialkot",          "lat": 32.4945, "lon": 74.5229, "urban": False},
        {"name": "Bahawalpur",       "lat": 29.3956, "lon": 71.6836, "urban": False},
        {"name": "Sargodha",         "lat": 32.0836, "lon": 72.6711, "urban": False},
        {"name": "Rahim Yar Khan",   "lat": 28.4202, "lon": 70.2952, "urban": False},
    ],
    "Sindh": [
        {"name": "Karachi",          "lat": 24.8607, "lon": 67.0011, "urban": True},
        {"name": "Hyderabad",        "lat": 25.3960, "lon": 68.3578, "urban": True},
        {"name": "Sukkur",           "lat": 27.7052, "lon": 68.8574, "urban": False},
        {"name": "Larkana",          "lat": 27.5570, "lon": 68.2247, "urban": False},
        {"name": "Mirpur Khas",      "lat": 25.5270, "lon": 69.0138, "urban": False},
        {"name": "Nawabshah",        "lat": 26.2442, "lon": 68.4100, "urban": False},
        {"name": "Jacobabad",        "lat": 28.2769, "lon": 68.4514, "urban": False},
        {"name": "Dadu",             "lat": 26.7319, "lon": 67.7750, "urban": False},
        {"name": "Tharparkar",       "lat": 24.7161, "lon": 70.2430, "urban": False},
    ],
    "KPK": [
        {"name": "Peshawar",         "lat": 34.0151, "lon": 71.5249, "urban": True},
        {"name": "Mardan",           "lat": 34.1986, "lon": 72.0404, "urban": False},
        {"name": "Abbottabad",       "lat": 34.1463, "lon": 73.2117, "urban": False},
        {"name": "Swat",             "lat": 35.2227, "lon": 72.4258, "urban": False},
        {"name": "Kohat",            "lat": 33.5869, "lon": 71.4414, "urban": False},
        {"name": "Bannu",            "lat": 32.9892, "lon": 70.6060, "urban": False},
        {"name": "Dera Ismail Khan", "lat": 31.8314, "lon": 70.9019, "urban": False},
        {"name": "Mansehra",         "lat": 34.3330, "lon": 73.2000, "urban": False},
        {"name": "Charsadda",        "lat": 34.1480, "lon": 71.7308, "urban": False},
    ],
    "Balochistan": [
        {"name": "Quetta",           "lat": 30.1798, "lon": 66.9750, "urban": True},
        {"name": "Turbat",           "lat": 26.0022, "lon": 63.0440, "urban": False},
        {"name": "Khuzdar",          "lat": 27.8120, "lon": 66.6170, "urban": False},
        {"name": "Gwadar",           "lat": 25.1264, "lon": 62.3225, "urban": False},
        {"name": "Chaman",           "lat": 30.9200, "lon": 66.4500, "urban": False},
        {"name": "Zhob",             "lat": 31.3416, "lon": 69.4481, "urban": False},
        {"name": "Loralai",          "lat": 30.3700, "lon": 68.5900, "urban": False},
        {"name": "Sibi",             "lat": 29.5430, "lon": 67.8770, "urban": False},
        {"name": "Nushki",           "lat": 29.5520, "lon": 66.0200, "urban": False},
    ],
}

# Flat list + lookup maps
DISTRICTS: list[str] = []
DISTRICT_PROVINCE_MAP: dict[str, str] = {}
DISTRICT_INFO_MAP: dict[str, dict] = {}

for _prov, _dlist in PAKISTAN_DISTRICTS.items():
    for _d in _dlist:
        DISTRICTS.append(_d["name"])
        DISTRICT_PROVINCE_MAP[_d["name"]] = _prov
        DISTRICT_INFO_MAP[_d["name"]] = {**_d, "province": _prov}

# ---------------------------------------------------------------------------
# Union Councils — 5 per district (180 total)
# ---------------------------------------------------------------------------

UNION_COUNCILS: dict[str, list[str]] = {
    # Punjab
    "Lahore":           ["Shahdara", "Ravi", "Nishtar", "Gulberg", "Samanabad"],
    "Faisalabad":       ["Madina Town", "Iqbal Town", "Lyallpur", "Millat", "Jinnah"],
    "Multan":           ["Shah Rukn-e-Alam", "Qasim Bela", "Shalimar", "Cantt", "Gulgasht"],
    "Rawalpindi":       ["Rawat", "Taxila", "Gujar Khan", "Murree", "Kahuta"],
    "Gujranwala":       ["Kamoke", "Wazirabad", "Hafizabad", "Gujrat", "Gondlanwala"],
    "Sialkot":          ["Daska", "Sambrial", "Pasrur", "Narowal", "Zafarwal"],
    "Bahawalpur":       ["Ahmadpur East", "Hasilpur", "Khairpur Tamewali", "Yazman", "Uch Sharif"],
    "Sargodha":         ["Bhalwal", "Sahiwal", "Sillanwali", "Kot Momin", "Shahpur"],
    "Rahim Yar Khan":   ["Sadiqabad", "Liaquatpur", "Khanpur", "Bhong", "Machka"],
    # Sindh
    "Karachi":          ["Lyari", "Korangi", "Malir", "Orangi", "Saddar"],
    "Hyderabad":        ["Latifabad", "Qasimabad", "Hirabad", "City", "Tando Allahyar"],
    "Sukkur":           ["Rohri", "Pano Aqil", "Saleh Pat", "Ghotki", "Ubauro"],
    "Larkana":          ["Dokri", "Kambar", "Shahdadkot", "Warah", "Mehar"],
    "Mirpur Khas":      ["Digri", "Kot Ghulam Muhammad", "Tando Jan Muhammad", "Jhuddo", "Umerkot"],
    "Nawabshah":        ["Sakrand", "Moro", "Kandiaro", "Mehrabpur", "Daur"],
    "Jacobabad":        ["Thul", "Garhi Khairo", "Kashmor", "Kandhkot", "Tangwani"],
    "Dadu":             ["Johi", "Mehar", "Khairpur Nathan Shah", "Sehwan", "Bubak"],
    "Tharparkar":       ["Mithi", "Islamkot", "Diplo", "Chachro", "Nagarparkar"],
    # KPK
    "Peshawar":         ["Hayatabad", "University Town", "Cantonment", "Gulbahar", "Badaber"],
    "Mardan":           ["Rustam", "Takht Bhai", "Katlang", "Shergarh", "Hoti"],
    "Abbottabad":       ["Havelian", "Haripur", "Ghazi", "Tarbela", "Banda Daud Shah"],
    "Swat":             ["Mingora", "Matta", "Kabal", "Khwazakhela", "Bahrain"],
    "Kohat":            ["Lachi", "Hangu", "Tal", "Doaba", "Gumbat"],
    "Bannu":            ["Domel", "Lakki Marwat", "Serai Naurang", "Jani Khel", "Mirali"],
    "Dera Ismail Khan": ["Kulachi", "Paharpur", "Darazinda", "Prova", "Kirri Shamozai"],
    "Mansehra":         ["Balakot", "Oghi", "Battal", "Darband", "Shinkiari"],
    "Charsadda":        ["Shabqadar", "Tangi", "Prang", "Umarzai", "Sardaryab"],
    # Balochistan
    "Quetta":           ["Sariab", "Satellite Town", "Jinnah Town", "Brewery Road", "Hazara Town"],
    "Turbat":           ["Mand", "Dasht", "Tump", "Hoshab", "Buleda"],
    "Khuzdar":          ["Wadh", "Zehri", "Ornach", "Naal", "Moola"],
    "Gwadar":           ["Pasni", "Ormara", "Jiwani", "Suntsar", "Pishukan"],
    "Chaman":           ["Killa Abdullah", "Gulistan", "Dobandi", "Spin Boldak", "Nushki Road"],
    "Zhob":             ["Muslim Bagh", "Qamardin Karez", "Khanozai", "Sherani", "Musa Khel"],
    "Loralai":          ["Bori", "Duki", "Mekhtar", "Khost", "Sanjawi"],
    "Sibi":             ["Lehri", "Harnai", "Ziarat", "Sangan", "Kachhi"],
    "Nushki":           ["Dalbandin", "Chagai", "Nokundi", "Taftan", "Mashkel"],
}

# ---------------------------------------------------------------------------
# Health Facilities — 3 per district (108 total: DHQ + RHC + BHU)
# ---------------------------------------------------------------------------

HEALTH_FACILITIES: list[dict] = []
_fac_counter = 1
for _prov, _dlist in PAKISTAN_DISTRICTS.items():
    for _d in _dlist:
        _dn = _d["name"]
        _lat, _lon = _d["lat"], _d["lon"]
        for _ftype, _dlat, _dlon in [
            ("DHQ", 0.000,  0.000),
            ("RHC", 0.030,  0.025),
            ("BHU", 0.060, -0.020),
        ]:
            HEALTH_FACILITIES.append({
                "id":       f"HF{_fac_counter:03d}",
                "name":     f"{_ftype} {_dn}",
                "type":     _ftype,
                "district": _dn,
                "province": _prov,
                "lat":      round(_lat + _dlat, 4),
                "lon":      round(_lon + _dlon, 4),
            })
            _fac_counter += 1

# ---------------------------------------------------------------------------
# Enumerators — 3 per district (108 total)
# ---------------------------------------------------------------------------

_F_FIRST = [
    "Ayesha", "Fatima", "Zainab", "Maryam", "Sana", "Nadia", "Hina",
    "Rabia", "Amna", "Saima", "Bushra", "Rukhsana", "Nasreen", "Shazia",
    "Noor", "Sadia", "Uzma", "Samina", "Tahira", "Gulnaz",
]
_M_FIRST = [
    "Muhammad", "Ali", "Ahmed", "Hassan", "Usman", "Bilal", "Hamza",
    "Tariq", "Imran", "Asif", "Khalid", "Naveed", "Shahid", "Waseem",
    "Omer", "Zubair", "Faisal", "Rizwan", "Adnan", "Kamran",
]
_SNAMES = [
    "Khan", "Ahmed", "Malik", "Iqbal", "Raza", "Hussain", "Butt",
    "Chaudhry", "Sheikh", "Mirza", "Siddiqui", "Qureshi", "Ansari",
    "Baloch", "Mengal", "Marri", "Bugti", "Khattak", "Yousafzai", "Afridi",
]

_rnd.seed(99)
ENUMERATORS: list[dict] = []
_enum_counter = 1
for _prov, _dlist in PAKISTAN_DISTRICTS.items():
    for _d in _dlist:
        _dn = _d["name"]
        for _i in range(3):
            _sex   = "female" if _i == 0 else "male"
            _first = _rnd.choice(_F_FIRST if _sex == "female" else _M_FIRST)
            _last  = _rnd.choice(_SNAMES)
            ENUMERATORS.append({
                "id":       f"E{_enum_counter:03d}",
                "name":     f"{_first} {_last}",
                "district": _dn,
                "province": _prov,
                "sex":      _sex,
            })
            _enum_counter += 1

# ---------------------------------------------------------------------------
# Names — bilingual (English transliteration + Urdu script for DQ injection)
# ---------------------------------------------------------------------------

URDU_NAMES_FEMALE = [
    "Ayesha", "Fatima", "Zainab", "Maryam", "Sana", "Nadia", "Hina",
    "Rabia", "Amna", "Saima", "Bushra", "Rukhsana", "Nasreen", "Shazia",
    "Noor", "Sadia", "Uzma", "Samina", "Tahira", "Gulnaz", "Parveen",
    "Shahida", "Razia", "Kausar", "Shahnaz", "Farida", "Nagina", "Zara",
    # Urdu script variants (injected as DQ)
    "\u0639\u0627\u0626\u0634\u06c1", "\u0641\u0627\u0637\u0645\u06c1",
    "\u0632\u06cc\u0646\u0628", "\u0645\u0631\u06cc\u0645",
    "\u062b\u0646\u0627\u0621", "\u0646\u0627\u062f\u06cc\u06c1",
]

URDU_NAMES_MALE = [
    "Muhammad", "Ali", "Ahmed", "Hassan", "Usman", "Bilal", "Hamza",
    "Tariq", "Imran", "Asif", "Khalid", "Naveed", "Shahid", "Waseem",
    "Omer", "Zubair", "Faisal", "Rizwan", "Adnan", "Kamran", "Arif",
    "Sajid", "Waqar", "Tanveer", "Mushtaq", "Pervaiz", "Ghulam", "Abdul",
    # Urdu script variants
    "\u0645\u062d\u0645\u062f", "\u0639\u0644\u06cc",
    "\u0627\u062d\u0645\u062f", "\u062d\u0633\u0646",
    "\u0639\u062b\u0645\u0627\u0646", "\u0628\u0644\u0627\u0644",
]

URDU_SURNAMES = [
    "Khan", "Ahmed", "Malik", "Iqbal", "Raza", "Hussain", "Butt",
    "Chaudhry", "Sheikh", "Mirza", "Siddiqui", "Qureshi", "Ansari",
    "Baloch", "Mengal", "Marri", "Bugti", "Khattak", "Yousafzai", "Afridi",
    "Bhutto", "Zardari", "Leghari", "Talpur", "Gilani",
    # Urdu script
    "\u062e\u0627\u0646", "\u0627\u062d\u0645\u062f",
    "\u0645\u0644\u06a9", "\u0627\u0642\u0628\u0627\u0644",
    "\u0628\u0644\u0648\u0686", "\u062e\u0679\u06a9",
]

# ---------------------------------------------------------------------------
# Bilingual field value mappings (English -> Urdu script)
# ---------------------------------------------------------------------------

URDU_WATER_SOURCES = {
    "piped":    "\u067e\u0627\u0626\u067e",
    "handpump": "\u06c1\u06cc\u0646\u0688 \u067e\u0645\u067e",
    "well":     "\u06a9\u0646\u0648\u0627\u06ba",
    "tanker":   "\u0679\u06cc\u0646\u06a9\u0631",
    "river":    "\u062f\u0631\u06cc\u0627",
    "canal":    "\u0646\u06c1\u0631",
}

URDU_SES_TIERS = {
    "low":    "\u06a9\u0645",
    "middle": "\u062f\u0631\u0645\u06cc\u0627\u0646\u06c1",
    "high":   "\u0632\u06cc\u0627\u062f\u06c1",
}

URDU_YES_NO = {
    0: "\u0646\u06c1\u06cc\u06ba",
    1: "\u06c1\u0627\u06ba",
}

# ---------------------------------------------------------------------------
# Data quality injection rates (deliberate, documented)
# ---------------------------------------------------------------------------

DATA_QUALITY_RATE = 0.15

DQ_RATES = {
    "bilingual_field":  0.15,
    "typo_district":    0.07,
    "bad_date_format":  0.08,
    "missing_gps":      0.04,
    "outlier_age":      0.03,
    "outlier_height":   0.02,
    "outlier_weight":   0.02,
    "duplicate_hh":     0.045,
    "missing_muac":     0.06,
    "missing_hb":       0.08,
    "short_interview":  0.05,
    "enum_id_typo":     0.05,
}

