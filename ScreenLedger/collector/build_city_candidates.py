#!/usr/bin/env python3
"""Generate a *candidate* 500-location priority list, not a certified District roster.

Default mode uses geographically spread, hand-curated Indian cities/towns and a
major-city-first heuristic. For stronger population-based priority, download the
GeoNames cities15000.zip separately (CC BY 4.0) and pass --geonames ZIP_OR_TXT.

No contact with district.in is needed.
"""
from __future__ import annotations
import argparse
import csv
import io
import itertools
import zipfile
from pathlib import Path
from district_extractor import slugify_city

# Starting priorities are heuristic. Delhi-NCR is deliberately one region:
# don't separately count Delhi, Noida, Gurugram, Ghaziabad, Faridabad.
FIRST = """
mumbai,delhi-ncr,bengaluru,hyderabad,chennai,pune,kolkata,ahmedabad,
jaipur,lucknow,surat,indore,visakhapatnam,kanpur,nagpur,patna,vadodara,
coimbatore,ludhiana,agra,nashik,rajkot,kochi,bhopal,guwahati,chandigarh,
varanasi,vijayawada,thiruvananthapuram,madurai,raipur,amritsar,jodhpur,
mysuru,allahabad,ranchi,meerut,gwalior,kota,jabalpur,hubli,aurangabad,
udaipur,mangalore,bhubaneswar,thrissur,kollam,warangal,guntur,solapur,
trichy,vellore,tiruppur,salem,kurnool,nellore,rajahmundry,kakinada,
bareilly,aligarh,moradabad,jalandhar,belgaum,ajmer,alwar,ujjain,rajkot,
kolhapur,shillong,gangtok,panaji,imphal,agartala,jammu,srinagar,dehradun,
haridwar,siliguri,durgapur,asansol,jamshedpur,howrah,erode,tirunelveli,
muzaffarpur,gaya,bikaner,bhilai,cuttack,anantapur,pondicherry
"""
# Regional candidate pool, NOT verified District cinema-city keys. Slugs may differ.
REGIONS = {
"Andhra Pradesh": "tirupati,eluru,ongole,kadapa,proddatur,adoni,nandyal,hindupur,tenali,chilakaluripet,chirala,machilipatnam,bhimavaram,tadepalligudem,srikakulam,vizianagaram,palasa,narasaraopet,amalapuram,gudivada,kavali,rayachoti,puttaparthi,dharmavaram,mandapeta,pithapuram,tuni,markapur,tanuku,vinukonda,parvathipuram,anakapalle,bobbili,palakollu,kandukur,kothapeta,kurnool",
"Telangana": "karimnagar,nizamabad,khammam,ramagundam,mahbubnagar,nalgonda,suryapet,miryalaguda,siddipet,adilabad,mancherial,kamareddy,sangareddy,medak,jagtial,bhongir,vikarabad,zaheerabad,wanaparthy,mahabubabad,peddapalli,armoor,korutla,sircilla,ibrahimpatnam,shadnagar,bodhan",
"Tamil Nadu": "thanjavur,dindigul,karur,nagercoil,thoothukudi,kumbakonam,cuddalore,hosur,sivakasi,kanchipuram,chengalpattu,tiruvannamalai,viluppuram,pudukottai,nagapattinam,mayiladuthurai,ramanathapuram,rajapalayam,virudhunagar,tenkasi,karaikudi,namakkal,pollachi,mettupalayam,udumalaipettai,ambur,ranipet,arakkonam,ooty,kodaikanal,dharmapuri,krishnagiri,tiruchengode,tirupattur,perambalur,ariyalur,theni,thoothukudi,neyveli,attur,thiruvallur,manapparai,palani,vaniyambadi",
"Karnataka": "tumakuru,shivamogga,davanagere,ballari,kalaburagi,vijayapura,bagalkot,raichur,bidar,hassan,mandya,chitradurga,udupi,karwar,hosapete,kolar,ramanagara,belagavi,hubballi,dharwad,bijapur,chikkamagaluru,gadag,haveri,koppal,yadgir,sindhanur,gangavathi,ranebennur,chikkaballapur,robertsonpet,basavakalyan,jamkhandi,ilkal,chintamani,madikeri,bhadravati,sirsi,puttur,bantwal,bhatkal,tarikere,gokak,athani",
"Kerala": "kozhikode,kannur,alappuzha,palakkad,kottayam,malappuram,kasaragod,kalpetta,thodupuzha,perinthalmanna,manjeri,thalassery,payyanur,koothuparamba,wadakkanchery,chalakudy,kodungallur,muvattupuzha,perumbavoor,angamaly,attingal,neyyattinkara,chirayinkeezhu,kayankulam,haripad,chengannur,adoor,punalur,cherthala,irinjalkuda,ottapalam,shoranur,ponnani,tirur,vatakara,koyilandy,thaliparamba,nileshwaram,kanhangad,kunnamkulam,guruvayur,aluva",
"Maharashtra": "akola,amaravati,jalgaon,dhule,nanded,latur,ahmednagar,sangli,satara,baramati,ichalkaranji,karad,panvel,kalyan,dombivli,vasai,virar,ulhasnagar,navi-mumbai,mirabhayandar,bhiwandi,ambernath,badlapur,pimpri-chinchwad,chinchwad,shirdi,beed,parbhani,osmanabad,buldhana,washim,wardha,gondia,bhandara,chandrapur,yavatmal,ratnagiri,sindhudurg,malvan,sawantwadi,alibag,mahad,pen,karjat,khopoli,manmad,malegaon,shrirampur,kopargaon,paithan,hingoli,basmat,bhusawal,pandharpur,khamgaon",
"Gujarat": "gandhinagar,jamnagar,bhavnagar,junagadh,anand,nadiad,bharuch,navsari,vapi,valsad,porbandar,morbi,gandhidham,bhuj,palanpur,mehsana,godhra,dahod,patan,veraval,amreli,surendranagar,botad,jetpur,ankleshwar,vyara,kalol,himmatnagar,modasa,mahuva,halol,khambhat,unai,umreth,dwarka,mandvi,rapar,mundra",
"Rajasthan": "bhilwara,pali,sikar,churu,jhunjhunu,hanumangarh,sri-ganganagar,barmer,jaisalmer,balotra,banswara,dungarpur,chittorgarh,pratapgarh,nagaur,beawar,kishangarh,tonk,sawai-madhopur,bundi,baran,jhalawar,dholpur,karoli,dausa,alwar,bharatpur,abu-road,mount-abu,rajsamand,phalodi,sujangarh,makrana,nimbahera,didwana,kuchaman-city",
"Madhya Pradesh": "sagar,ratlam,rewa,satna,katni,burhanpur,khandwa,chhindwara,betul,hoshangabad,narmadapuram,dewas,sehore,vidisha,guna,shivpuri,datia,morena,damoh,chhatarpur,tikamgarh,niwari,panna,mandla,seoni,balaghat,shahdol,umaria,anuppur,singrauli,neemuch,mandsaur,shajapur,rajgarh,narsinghpur,hardoi,khargone,barwani,alirajpur,jhabua,ashoknagar,itarsi,nagda,pipariya,maiher",
"Uttar Pradesh": "gorakhpur,saharanpur,muzaffarnagar,mathura,firozabad,etawah,mainpuri,ayodhya,faizabad,basti,azamgarh,azamgarh,ballia,jaunpur,ghazipur,mau,bhadohi,mirzapur,sonbhadra,prayagraj,pratapgarh,sultanpur,raebareli,unao,unnao,hardoi,shahjahanpur,pilibhit,badaun,sambhal,rampur,amroha,bulandshahr,baghpat,hapur,modinagar,khurja,noida,greater-noida,ghaziabad,gurugram,aligarh,hathras,kasganj,etah,kannauj,farrukhabad,auraiya,lakhimpur,barabanki,gonda,bahraich,shravasti,balrampur,sitapur,hamirpur,mahoba,banda,chitrakoot,jhansi,lalitpur,orai,maharajganj,deoria,kushinagar,ambedkar-nagar,mirzapur",
"Bihar": "darbhanga,bhagalpur,purnia,katihar,begusarai,munger,arrah,chapra,hajipur,motihari,bettiah,siwan,gopalganj,samastipur,madhubani,sitamarhi,araria,kishanganj,supaul,saharsa,madhepura,khagaria,banka,jamui,lakhisarai,sheikhpura,nawada,bihar-sharif,jehanabad,aurangabad-bihar,sasaram,buxar,kaimur,rohtas,bagaha,narkatiaganj,forbesganj,rosra,raghopur,rafiganj,daudnagar,barh,rajgir,bodhgaya",
"West Bengal": "bardhaman,burdwan,malda,english-bazar,balurghat,raiganj,jalpaiguri,alipurduar,cooch-behar,kalimpong,darjeeling,kurseong,jhargram,medinipur,midnapore,kharagpur,tamluk,haldia,contai,basirhat,bangaon,barasat,madhyamgram,habra,dum-dum,baranagar,serampore,chandannagar,hooghly,chinsurah,bandel,rishra,uttarpara,barrackpore,kalyani,naihati,halisahar,bhatpara,krishnanagar,ranaghat,shantipur,nabadwip,berhampore,murshidabad,bolpur,santiniketan,suri,rampurhat,purulia,bankura,bishnupur,katwa,kalna,arambagh,sainthia,islampur,rajnagar,baharampur,dhuliyan,memari,chakdaha,caning,canning,diamond-harbour,barasat",
"Odisha": "rourkela,sambalpur,berhampur,brahmapur,balasore,baleswar,baripada,jharsuguda,jeypore,koraput,rayagada,paradip,angul,dhenkanal,bhadrak,keonjhar,kendujhar,puri,konark,khordha,jatni,nayagarh,balangir,titlagarh,bargarh,boudh,sonepur,subarnapur,phulbani,chatrapur,asika,gunupur,udala,rajgangpur,sundargarh,brajarajnagar,khariar,khariar-road",
"Jharkhand": "bokaro,hazaribagh,ramgarh,giridih,deoghar,dumka,chaibasa,adityapur,chirkunda,phusro,jharia,koderma,chatra,latehar,lohardaga,gumla,simdega,khunti,medininagar,palamu,garhwa,sahibganj,pakur,godda,madhupur,mihijam,chakradharpur,seraikela",
"Chhattisgarh": "bilaspur,korba,rajnandgaon,jagdalpur,ambikapur,dhamtari,mahasamund,raigarh,janjgir,naila,champa,balod,kanker,manendragarh,kawardha,mungeli,bemetara,bhatapara,baloda-bazar,pendra,bijapur,kondagaon,dantewada,narayanpur,sukma,jashpur,baikunthpur,surajpur",
"Punjab": "bathinda,patiala,mohali,sas-nagar,pathankot,hoshiarpur,moga,barnala,firozpur,ferozepur,faridkot,muktsar,kapurthala,nawanshahr,shaheed-bhagat-singh-nagar,tarn-taran,batala,gurdaspur,malerkotla,sangrur,khanna,mandi-gobindgarh,phagwara,rajpura,abohar,facilka,fazilka,zira,sunam,dhuri,ropar,rupnagar,anandpur-sahib",
"Haryana": "panipat,karnal,sonipat,rohtak,hisar,ambala,panchkula,yamunanagar,kurukshetra,kaithal,jind,bhiwani,sirsa,fatehabad,palwal,rewari,narnaul,jhajjar,bahadurgarh,manesar,dharuhera,pehowa,thanesar,tohana,hansi,gohana,gohana,maham,kalanaur,sohna,ballabhgarh",
"Uttarakhand": "haldwani,rudrapur,kashipur,roorkee,rishikesh,mussoorie,nainital,almora,pithoragarh,bageshwar,champawat,tanakpur,kotdwar,pauri,srinagar-garhwal,tehri,uttarkashi,chamoli,gopeshwar,ranikhet,vikasnagar,kichha,sitarganj,jaspur,ramnagar,landour",
"Himachal Pradesh": "shimla,solan,mandi,dharamshala,palampur,kangra,hamirpur-himachal,una,nahan,bilaspur-himachal,kullu,manali,chamba,dalhousie,paonta-sahib,nalagarh,baddi,parwanoo,sundarnagar,rohru,rohru,rohru,kasauli",
"Assam": "dibrugarh,silchar,jorhat,tezpur,nagaon,tinsukia,barpeta,bongaigaon,diphu,dhubri,golaghat,nalbari,karimganj,sivasagar,sibsagar,north-lakhimpur,lakhimpur,margherita,lumding,guwahati,goalpara,hailakandi,rangia,biswanath-chariali,dergaon,mangaldoi,sonari,lakhipur,badarpur",
"Jammu & Kashmir": "anantnag,baramulla,sopore,budgam,pulwama,shopian,kulgam,bandipora,bijbehara,pampore,awantipora,udhampur,udhampur,kathua,samba,rajouri,poonch,reasi,doda,kishtwar,banihal,ramban,handwara,kupwara",
"Northeast / Other": "kohima,dimapur,mokokchung,tuensang,wokha,zunheboto,aizawl,lunglei,champhai,serchhip,itanagar,naharlagun,pasighat,tawang,ziro,tezu,bomdila,roing,agartala,udaipur-tripura,dharmanagar,kailashahar,belonia,khowai,ambassa,imphal,thoubal,bishnupur-manipur,churachandpur,kakching,moreh,gangtok,namchi,singtam,gyalshing,mangan,tadong,port-blair,car-nicobar,kavaratti,leh,kargil",
}

# See source: District movie landing page for these mentioned cities; not proof of a
# movie showing today. Only four slugs were separately checked for Ramayana via web.
SITE_MENTIONED = {slugify_city(x) for x in "mumbai delhi-ncr bengaluru hyderabad chennai pune kolkata ahmedabad jaipur lucknow indore vizag guntur vijayawada nellore anantapur kurnool kakinada trivandrum surat".split()}
MOVIE_CHECKED = {"mumbai", "delhi-ncr", "jaipur", "kolkata"}


def candidates():
    seen = set()
    for i, city in enumerate(FIRST.replace("\n", "").split(",")):
        city = city.strip()
        if not city:
            continue
        slug = slugify_city(city)
        if slug not in seen:
            seen.add(slug)
            yield (city, slug, "A", "curated_major_city")
    # Geographic round-robin: avoid the first 500 being concentrated in a few states.
    region_iters = [iter([x.strip() for x in cities.split(",") if x.strip()]) for cities in REGIONS.values()]
    for group in itertools.zip_longest(*region_iters):
        for city in group:
            if city is None:
                continue
            slug = slugify_city(city)
            if slug not in seen:
                seen.add(slug)
                yield (city, slug, "B", "curated_candidate")


def geo_data(path: Path):
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next((x for x in z.namelist() if x.endswith("cities15000.txt") or x.endswith("cities5000.txt")), None)
            if not name:
                raise ValueError("GeoNames ZIP must contain cities15000.txt or cities5000.txt")
            f = io.TextIOWrapper(z.open(name), encoding="utf-8")
            yield from parse_geonames_rows(csv.reader(f, delimiter="\t"))
    else:
        with path.open(encoding="utf-8") as f:
            yield from parse_geonames_rows(csv.reader(f, delimiter="\t"))


def parse_geonames_rows(rows):
    for r in rows:
        if len(r) > 14 and r[8] == "IN" and r[6] == "P":
            try: population = int(r[14])
            except ValueError: continue
            if population >= 15000:
                yield (r[2] or r[1], population, r[1])


def main():
    p = argparse.ArgumentParser(description="Generate up to 500 prioritized candidate Indian location slugs")
    p.add_argument("--count", type=int, default=500)
    p.add_argument("--geonames", type=Path, help="Optional cities15000.zip or cities15000.txt from download.geonames.org")
    p.add_argument("--out", type=Path, default=Path("cities_500_candidates.csv"))
    a = p.parse_args()
    if a.count < 1: p.error("--count must be positive")
    entries = list(candidates())
    if a.geonames:
        existing = {r[1] for r in entries}
        geocities = sorted(geo_data(a.geonames), key=lambda r: r[1], reverse=True)
        for name, pop, _ in geocities:
            slug = slugify_city(name)
            if slug not in existing:
                existing.add(slug)
                entries.append((name, slug, "C", "geonames_population_candidate"))
    selected = entries[:a.count]
    if len(selected) < a.count:
        raise ValueError(f"Only {len(selected)} candidate cities available; supply --geonames to reach {a.count}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "city", "slug", "tier", "district_evidence", "priority_basis"])
        writer.writeheader()
        for i, (city, slug, tier, basis) in enumerate(selected, 1):
            evidence = "ramayana_page_checked" if slug in MOVIE_CHECKED else ("district_site_mentioned" if slug in SITE_MENTIONED else "not_verified")
            writer.writerow({"rank": i, "city": city, "slug": slug, "tier": tier,
                             "district_evidence": evidence, "priority_basis": basis})
    print(f"Created {a.out}: {len(selected)} candidate locations; NOT a verified list of 500 District city keys")
    print(f"Web-checked Ramayana cities: {sum(1 for x in selected if x[1] in MOVIE_CHECKED)}")

if __name__ == "__main__":
    main()
