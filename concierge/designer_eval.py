"""Helpers worked out by talking, with the real models, on a made-up home.

The one check of the whole way a helper is made and lives: scripted conversations through
the real engine (`engine.send`, `engine.choose`, as a window would), with the model that
designs and Noir's own model. The user's side is fixed text, so each script is written to
hold whether the design model takes one turn more or one fewer: lines are said until the
card is up, and what is checked is what code ended up with and what was never done (no
helper made by talking, no file moved by a try-out, never "it's on" before the button).
Every word is printed to be read, since no check can judge the words.

Each conversation is a made-up person on a made-up home of their own, with the app's data
in a temporary folder beside it, so nothing of the user's is read, moved or written, and
every conversation starts from nothing. The people are test data: a bicycle repair shop,
a household, a beekeeper who is learning Japanese.

    python -m concierge.designer_eval [tag] [--only name ...] [--keep] [--forms] [--list]
    python -m concierge.designer_eval --plan codex --only thin

With no tag, the model that would design on this computer is the one played with. A model
goes on the designers list in models.yaml only when every check passes, several plays in
a row. `--only` plays the conversations named; `--keep` leaves the made-up homes behind;
`--forms` also prints each form the design model filled; `--list` names the conversations.
`--plan codex` plays with the user's own ChatGPT plan designing, through Codex: every turn
is charged to that plan, so it is for one conversation at a time. Ollama must be running,
with Noir set up.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from concierge import accounts as accounts_mod
from concierge import chores, noir, places, research, usage
from concierge import engine as engine_mod
from concierge.agents import builder, designer, parts, planner, store
from concierge.agents.builder import CARD, CREATE_IT, SAVE_CHANGES
from concierge.agents.designer import DESIGN_CONTEXT, TRY_OUT, DesignModel, talker_form
from concierge.catalog import ModelEntry
from concierge.engine import (CARRY_ON, CARRY_ON_YES, CHANGE_THE_RULE, DELETE_AGENT, DELETE_IT, DROP_IT, FIRST_PASS,
                              FIX_AGENT, GO_THROUGH, JUST_THIS_ONE, ONLY_NEW, RULE_FROM_MOVE, SWITCH_IT_ON, NoirEngine)
from concierge.events import AgentCard, AgentList, Error, NoirText, Progress, Question, Result, Thinking
from concierge.models import nice_name
from concierge.ollama import Ollama
from concierge.quick.agents import ANSWERED, BUBBLE, LEFT_OUT, UNTIL_UNHIGHLIGHT, QuickAgents

# The modules that ask where Desktop, Documents, Downloads and Pictures are. Each holds a
# reference of its own to the function that says so, and each must be given the made-up
# home's: with one left out, a run would look in the user's real folders.
ASK_FOR_PLACES = (places, builder, designer, parts)

# ---------------------------------------------------------------- the made-up people
# Test data, every word of it. Each folder is listed oldest first, and its files are
# written a minute apart, so the newest eight (what a try-out reads) are the last eight.

# Tomás Ferreira runs Spoke & Chain, a bicycle repair shop. His Downloads: what two parts
# suppliers send, bills for the shop, papers he wrote for customers, and whatever else
# landed there. Some of it is easy to take for the wrong thing: a quote he sent is no
# invoice from a supplier, a receipt is no bill, a delivery note is from a supplier too.
SHOP = {
    "label_printer_setup.exe": None,  # a program: nothing to read, the name says little
    "shop_radio_mix.mp3": None,  # a recording
    "kestrel_dealer_catalog_2026.pdf": ["Kestrel Cycles - Dealer Catalog 2026", "Frames, forks and complete bikes for independent shops",
                                        "Gravel: Kestrel Tarn, from $1,240 dealer price",
                                        "Order through your dealer account; minimum order 3 units."],
    "price_list_spring.xlsx": ["Spoke & Chain - repair price list, spring 2026", "Job", "Price", "Basic tune-up", "65",
                               "Wheel true", "25", "Brake bleed", "40", "Full overhaul", "180"],
    "staff_rota_november.docx": ["Spoke & Chain - staff rota, November", "Mon to Wed: Tomas, Ana", "Thu to Sat: Tomas, Lucas",
                                 "Sunday closed", "Lucas is off on the 14th"],
    "IMG_2207.jpg": ((150, 190, 235), (95, 120, 80)),  # a photo with no writing in it
    "recipe_feijoada.txt": ["Feijoada (6 servings)", "500 g black beans, soaked overnight; 300 g pork shoulder; 200 g smoked sausage",
                            "1. Simmer the beans for an hour. 2. Brown the meat with onion and garlic.",
                            "3. Add the meat and two bay leaves to the beans and simmer for two more hours."],
    "dentist_reminder.pdf": ["Harborview Dental - Appointment reminder", "Patient: Tomas Ferreira",
                             "Tuesday 24 November 2026, 8:30 am", "Please arrive 10 minutes early."],
    "quote_0412_okafor.pdf": ["QUOTE 0412", "From: Spoke & Chain Bicycle Repair   To: Daniel Okafor",
                              "Rear wheel rebuild with a new rim and spokes, labour included",
                              "Total: $185.00   Valid for 30 days", "Reply to this email to book the job."],
    "repair_order_3318_brandt.pdf": ["REPAIR ORDER 3318", "Spoke & Chain Bicycle Repair", "Customer: Helen Brandt   Bike: Trek FX 2",
                                     "Work: replace chain and cassette, adjust rear derailleur",
                                     "Parts $74.00   Labour $45.00   Total $119.00", "Ready for pickup on Friday."],
    "card_terminal_statement_oct.pdf": ["SwiftPay Merchant Services - Monthly statement", "Merchant: Spoke & Chain Bicycle Repair",
                                        "October 2026: 214 card payments, $9,870.00 processed",
                                        "Fees of $236.88 were taken from your payouts. No payment is due."],
    "invoice_velo_parts_88120.pdf": ["INVOICE 88120", "Velo Parts Wholesale Inc.   Bill to: Spoke & Chain Bicycle Repair",
                                     "40 x inner tube 700c   20 x brake pad set   10 x chain 11-speed",
                                     "Total due: $612.40   Terms: net 30   Due 12 December 2026"],
    "kestrel_cycles_invoice_K5521.pdf": ["Kestrel Cycles LLC - INVOICE K-5521", "Sold to: Spoke & Chain Bicycle Repair, dealer account 2207",
                                         "2 x Kestrel Tarn gravel bike, size M", "Amount due: $2,480.00   Due 5 December 2026"],
    "electricity_shop_october.pdf": ["Portland General Electric - Business Bill",
                                     "Account 77-310-442   Spoke & Chain Bicycle Repair, 1418 SE Alder St",
                                     "Billing period: 1 October to 31 October 2026   Usage: 688 kWh",
                                     "Amount due: $104.12   Due date: 24 November 2026"],
    "velo_parts_delivery_note_88120.pdf": ["DELIVERY NOTE for order 88120", "Velo Parts Wholesale Inc.   Deliver to: Spoke & Chain Bicycle Repair",
                                           "Shipped 9 November 2026 in 2 boxes: inner tubes, brake pads, chains",
                                           "Please check the contents and report anything missing within 5 days."],
    "water_bill_shop_q3.pdf": ["Portland Water Bureau - Statement", "Account 20-118-903   1418 SE Alder St (commercial)",
                               "Billing period: 1 July to 30 September 2026", "Amount due: $88.60   Due date: 20 November 2026"],
    "receipt_hardware_store.pdf": ["Alder Street Hardware - Receipt", "13 November 2026   Paid by card ending 3090",
                                   "2 x hex key set  $18.00   1 x degreaser 1 gal  $22.50", "Total paid: $40.50   Thank you!"],
    "whiteboard_jobs.png": ["Jobs this week", "Mon: Brandt - chain", "Tue: Okafor wheel", "Thu: Kestrel delivery", "Fri: order tubes"],
}
# What Tomás wants of his newest files, by a word of the folder each belongs in ("" = it
# stays where it is). Held against a try-out to find something for him to correct.
SHOP_WANTS = {"invoice_velo_parts_88120.pdf": "velo", "kestrel_cycles_invoice_K5521.pdf": "kestrel",
              "velo_parts_delivery_note_88120.pdf": "velo", "electricity_shop_october.pdf": "bill",
              "water_bill_shop_q3.pdf": "bill", "receipt_hardware_store.pdf": "", "whiteboard_jobs.png": ""}
# What he says when a file came out otherwise, in his own words.
SHOP_SAYS = {
    "invoice_velo_parts_88120.pdf": "the velo parts invoice should go in the velo parts folder, its from them",
    "kestrel_cycles_invoice_K5521.pdf": "the kestrel invoice goes with kestrel, not anywhere else",
    "velo_parts_delivery_note_88120.pdf": "the delivery note is from velo parts too, it goes with their stuff",
    "electricity_shop_october.pdf": "the electricity one is a bill i have to pay, that goes in bills",
    "water_bill_shop_q3.pdf": "the water one is a bill i have to pay, that goes in bills",
    "receipt_hardware_store.pdf": "the hardware store receipt isnt a bill, i already paid that. receipts stay where they are",
    "whiteboard_jobs.png": "the whiteboard photo should stay where it is, thats just my list of jobs",
}
# And when the first try-out was all he wanted: something more, so there is a change to make.
SHOP_ALSO = ("receipt_hardware_store.pdf", "bill",
             "almost. receipts for things i already paid can go in bills too, i keep those together")
# The same files as he wants them when all that his suppliers send goes into one folder,
# and what he says about the first one that came out otherwise.
SHOP_WANTS_TWO = {"invoice_velo_parts_88120.pdf": "suppliers", "kestrel_cycles_invoice_K5521.pdf": "suppliers",
                  "velo_parts_delivery_note_88120.pdf": "suppliers", "electricity_shop_october.pdf": "bills",
                  "water_bill_shop_q3.pdf": "bills", "receipt_hardware_store.pdf": "", "whiteboard_jobs.png": ""}
SHOP_SAYS_TWO = {
    "suppliers": "no, what velo parts and kestrel send me goes in Suppliers, their invoices too. Bills is only for "
                 "things like electricity and water",
    "bills": "the electricity and water ones are bills i have to pay, they go in Bills",
    "": "the receipt and the whiteboard photo should stay where they are",
}
# What lands in the shop's Downloads later.
SHOP_LATER = {
    "invoice_velo_parts_88342.pdf": ["INVOICE 88342", "Velo Parts Wholesale Inc.   Bill to: Spoke & Chain Bicycle Repair",
                                     "30 x tyre 700x32   12 x bottom bracket", "Total due: $841.00   Terms: net 30   Due 20 December 2026"],
    "concert_tickets_december.pdf": ["Crystal Ballroom - e-tickets", "Order 5521907   2 x general admission",
                                     "Saturday 12 December 2026, doors 7 pm", "Show this page at the door."],
    "warranty_registration_truing_stand.pdf": ["Park Tool - Warranty registration", "Product: TS-4.2 professional truing stand   Serial PT-448120",
                                               "Registered to: Spoke & Chain Bicycle Repair on 10 November 2026",
                                               "Limited lifetime warranty. Keep this page."],
    "warranty_registration_compressor.pdf": ["Makita - Warranty registration", "Product: MAC2400 air compressor   Serial 2207-88120",
                                             "Registered to: Spoke & Chain Bicycle Repair on 14 November 2026",
                                             "3 year limited warranty. Keep this confirmation."],
    "staff_rota_december.docx": ["Spoke & Chain - staff rota, December", "Mon to Wed: Tomas, Ana", "Thu to Sat: Tomas, Lucas",
                                 "Closed 24 to 26 December"],
    "price_list_summer.xlsx": ["Spoke & Chain - repair price list, summer 2027", "Job", "Price", "Basic tune-up", "70",
                               "Wheel true", "28", "Full overhaul", "195"],
    "business_tax_notice_2026.pdf": ["City of Portland Revenue Division - Business tax notice", "Account BL-220718   Spoke & Chain Bicycle Repair",
                                     "Business licence tax for 2026: $412.00", "Due 15 December 2026."],
    "invoice_kestrel_K5609.pdf": ["Kestrel Cycles LLC - INVOICE K-5609", "Sold to: Spoke & Chain Bicycle Repair, dealer account 2207",
                                  "1 x Kestrel Tarn frame set, size L", "Amount due: $890.00   Due 9 January 2027"],
}

# The Okonkwo-Reyes household: two parents, two children, a dog. Their Downloads, the
# folder where they keep the house's papers, and the manuals of what is in the house.
HOUSE = {
    "printer_driver_setup.exe": None,
    "bedtime_story_podcast.mp3": None,
    "IMG_0931.jpg": ((235, 180, 130), (70, 80, 95)),
    "recipe_jollof_rice.txt": ["Jollof rice (4 servings)", "2 cups long grain rice, 4 tomatoes, 2 red peppers, 1 scotch bonnet, 1 onion",
                               "1. Blend the tomatoes and peppers. 2. Fry the onion, add the blend and cook it down.",
                               "3. Add stock and the rice, cover and steam for 30 minutes."],
    "holiday_booking_lisbon.pdf": ["Sunway Travel - Booking confirmation", "Booking ref SW-771245   Okonkwo-Reyes family, 2 adults 2 children",
                                   "Lisbon, 12 to 19 April 2027, Hotel Avenida, breakfast included",
                                   "The balance of $1,940.00 is due by 1 March 2027."],
    "birthday_party_invite.docx": ["You're invited!", "Kemi turns 8", "Saturday 5 December, 2 pm, Linden Community Hall",
                                   "RSVP to Adaeze by 28 November"],
    "school_newsletter_november.pdf": ["Linden Primary School - November newsletter", "Parents' evening is on Tuesday 24 November, 4 to 7 pm.",
                                       "Year 4 trip to the Science Museum on 3 December.",
                                       "Winter fair: Friday 11 December, cake donations welcome."],
    "gas_bill_november.pdf": ["NorthGas - Your gas bill", "Account 4410-2291   27 Linden Road",
                              "Billing period: 10 October to 9 November 2026", "Amount due: $96.40   Due date: 30 November 2026"],
    "swimming_lessons_timetable.pdf": ["Linden Leisure Centre - Children's swimming, winter term", "Stage 3: Saturdays 9:30 am   Stage 5: Saturdays 10:15 am",
                                       "Term starts 9 January 2027. Bring goggles."],
    "phone_bill_october.pdf": ["Telia Mobile - Monthly bill", "Account 88-120-553   2 lines", "October 2026 charges: $64.00",
                               "Amount due: $64.00, taken by direct debit on 22 November 2026"],
    "school_dinner_menu_december.pdf": ["Linden Primary School - Lunch menu, December", "Week 1: pasta bake, fish fingers, vegetable curry, roast chicken, pizza",
                                        "A vegetarian option every day. The menu may change."],
    "piano_lesson_invoice.pdf": ["Clara Whitfield, piano teacher - Invoice 118", "To: A. Okonkwo, for Kemi's lessons",
                                 "6 lessons in November at $28 = $168.00", "Please pay by bank transfer by 5 December 2026."],
    "screenshot_parking_fine.png": ["City Parking Services", "Penalty charge notice", "Vehicle: KX21 RTE", "Amount: $50 if paid by 2 Dec"],
    "water_bill_autumn.pdf": ["Linden Water - Bill", "Account 2207-118   27 Linden Road", "1 August to 31 October 2026",
                              "Amount due: $71.25   Due date: 28 November 2026"],
}
HOUSE_PAPERS = {
    "home_insurance_renewal.pdf": ["Northgate Insurance - Home policy renewal", "Policy HP-448120   Adaeze Okonkwo and Miguel Reyes, 27 Linden Road",
                                   "Renewal premium: $1,184.00 for 1 January to 31 December 2027",
                                   "Reply or pay by 15 December 2026 to keep your cover."],
    "school_trip_permission.docx": ["Linden Primary School - Trip permission", "Year 4 visit to the Science Museum, Thursday 3 December 2026",
                                    "Cost: $12 per child. A packed lunch is needed.", "Return the signed slip by Friday 27 November."],
    "car_service_invoice.pdf": ["Reyes Auto - Service invoice 2291", "Toyota Corolla, annual service and new brake pads",
                                "Total: $386.00, paid by card on 6 November 2026", "Next service due November 2027."],
    "council_tax_letter.pdf": ["City Council - Property tax notice", "27 Linden Road   Reference 7701-2291",
                               "Second instalment: $742.00, due 1 December 2026", "Pay online or at any post office."],
    "vet_vaccination_record.pdf": ["Linden Vets - Vaccination record", "Patient: Biscuit (dog, beagle)   Owner: M. Reyes",
                                   "Rabies and distemper boosters given 2 November 2026", "Next boosters due November 2027."],
}
HOUSE_PAPERS_LATER = {
    "broadband_contract_renewal.pdf": ["FibreNorth - Contract renewal", "Account FN-2291-07   27 Linden Road",
                                       "Your 24-month contract ends on 31 January 2027.",
                                       "New price from February: $54 a month. To cancel or switch, call by 10 January 2027."],
}
MANUALS = {
    "washing_machine_manual.pdf": ["Bosch Serie 6 Washing Machine - Instructions", "Daily wash: choose Cottons 40 and press Start.",
                                   "Detergent drawer: pull it out fully, press the release and rinse it under warm water once a month.",
                                   "Drain pump filter: open the flap at the bottom right, unscrew the filter slowly, let the water run into a tray. Clean it every three months.",
                                   "Error E18: the water is not draining. Clean the drain pump filter and check the hose for kinks."],
    "boiler_quick_guide.pdf": ["Vaillant ecoTEC boiler - Quick guide", "The pressure should be between 1.0 and 1.5 bar when the heating is cold.",
                               "To top up the pressure: open both valves of the filling loop under the boiler until the gauge shows 1.3 bar, then close both valves.",
                               "Fault F28: ignition failed. Press reset once; if it comes back, call the installer.",
                               "The annual service is due every October."],
    "oven_instructions.pdf": ["Neff built-in oven - Instructions", "To bake: turn the dial to CircoTherm, set the temperature, wait for the light to go out.",
                              "Cleaning: choose EasyClean, pour 400 ml of water with a drop of washing-up liquid onto the oven floor, 25 minutes.",
                              "Child lock: hold the key button for 4 seconds."],
    "router_notes.txt": ["Home internet notes", "Router: FibreNorth Hub 3, in the hall cupboard.",
                         "To restart it: unplug it for 30 seconds, plug it back in, wait 3 minutes for the white light.",
                         "Guest wifi name: LindenGuest. If the light is red, call FibreNorth on 0800 555 0142."],
    "smoke_alarm_leaflet.docx": ["FireAngel smoke alarm - Leaflet", "Test the alarm every week by pressing the centre button for 3 seconds.",
                                 "A chirp every 40 seconds means the battery is low: the battery is sealed, so replace the alarm.",
                                 "Replace the whole alarm after 10 years; the date is printed on its side."],
}

# The Han family's Downloads, for the conversation in Korean: letters from the child's
# school, bills, and the usual odds and ends, most of it in Korean.
KOREAN_HOME = {
    "프린터_설치.exe": None,
    "가족사진_추석.jpg": ((230, 190, 150), (90, 110, 70)),
    "제주_여행_일정.txt": ["제주도 가족여행 일정 (12월 20일 ~ 23일)", "첫째 날: 김포 출발 09:10, 렌터카 수령, 협재 해변",
                       "둘째 날: 한라산 영실 코스", "셋째 날: 성산일출봉, 우도"],
    "김치찌개_레시피.txt": ["김치찌개 (2인분)", "돼지고기 200g, 묵은지 2컵, 양파 반 개, 두부 반 모",
                       "1. 돼지고기를 볶는다. 2. 김치를 넣고 5분 더 볶는다. 3. 물 3컵을 넣고 20분 끓인다."],
    "영화_예매_확인.txt": ["CGV 예매 확인", "예매번호 7714-2209", "12월 5일 토요일 오후 2시 10분, 5관", "성인 2명, 어린이 1명"],
    "가정통신문_11월.docx": ["한빛초등학교 가정통신문 (11월)", "학부모 상담 주간: 11월 23일 ~ 27일", "4학년 현장체험학습: 12월 3일 국립과천과학관",
                        "겨울방학식: 12월 24일"],
    "전기요금_청구서_10월.txt": ["한국전력공사 전기요금 청구서", "고객번호 07-2211-884", "사용기간: 2026년 10월 1일 ~ 10월 31일",
                          "청구금액: 48,200원   납부기한: 2026년 11월 25일"],
    "급식_식단표_12월.docx": ["한빛초등학교 12월 급식 식단표", "1주: 잡곡밥, 미역국, 불고기, 배추김치", "2주: 카레라이스, 계란국, 깍두기",
                        "알레르기 유발 식품은 번호로 표시합니다."],
    "도시가스_요금_11월.txt": ["서울도시가스 요금 청구서", "고객번호 3301-77-0421", "사용기간: 2026년 10월 10일 ~ 11월 9일",
                         "청구금액: 62,750원   납부기한: 2026년 11월 30일"],
    "internet_bill_november.pdf": ["KT Internet - Monthly bill", "Account 1120-553-88", "November 2026 charges: 38,500 won",
                                   "Amount due: 38,500 won   Due date: 28 November 2026"],
    "방과후_수업_안내.docx": ["한빛초등학교 방과후 수업 안내", "로봇 과학: 화요일 오후 2시 ~ 3시 30분", "신청 기간: 11월 30일까지",
                        "수강료: 분기 60,000원"],
}
KOREAN_WANTS = {"가정통신문_11월.docx": "학교", "급식_식단표_12월.docx": "학교", "방과후_수업_안내.docx": "학교",
                "전기요금_청구서_10월.txt": "고지서", "도시가스_요금_11월.txt": "고지서", "internet_bill_november.pdf": "고지서",
                "영화_예매_확인.txt": "", "김치찌개_레시피.txt": ""}

# Ines Marchetti keeps bees, is the secretary of her beekeeping club and is learning
# Japanese. Her Pictures are photos of hives; the rest is what a hobby leaves behind.
HOBBY_DOWNLOADS = {
    "club_newsletter_autumn.pdf": ["Willow Valley Beekeepers - Autumn newsletter", "Honey show: Saturday 21 November, village hall",
                                   "Winter feeding: fondant from December, never syrup in the cold.",
                                   "Subscriptions for 2027 are due in January."],
    "honey_label_draft.png": ["Ines's Garden Honey", "Raw wildflower honey", "340 g", "Willow Valley"],
    "jlpt_n4_vocabulary.pdf": ["JLPT N4 vocabulary list, part 3", "忙しい (isogashii) - busy", "楽しい (tanoshii) - fun", "会議 (kaigi) - meeting",
                               "天気 (tenki) - weather"],
    "varroa_treatment_order.pdf": ["Thorne Beekeeping Supplies - Order confirmation", "Order 220718: 2 x oxalic acid treatment, 1 x hive tool",
                                   "Total $41.80, paid by card. Dispatched 12 November 2026."],
}
HOBBY_PICTURES = {f"IMG_30{number}.jpg": ((120 + number, 170, 230 - number), (70 + number, 110, 60)) for number in range(11, 23)}


# Words that say the helper exists or runs. Before the card's button is pressed that is
# never true, and three of four models said it anyway in the first probe.
SAYS_DONE = re.compile(r"\b(is|it'?s|are) (now |already )?(on|active|running|switched on|turned on|created|up and running)\b"
                       r"|\bi('ve| have)? (just )?(created|switched it on|turned it on|started it|set it up)\b",
                       re.IGNORECASE)
# The same words about later, which claim nothing: "files that arrive while it is running",
# "once it is on". Looked for just in front of a match.
ABOUT_LATER = re.compile(r"\b(while|when|whenever|once|after|if|until|as long as|as soon as)\b[^.!?,;]{0,25}$", re.IGNORECASE)
# Other things a line is looked at for: that something is left alone, that something
# can't be done, and that it is in Korean.
SAYS_STAYS = re.compile(r"stay|leav|alone|won'?t|will not|not (be )?(mov|touch)|untouched|ignor|only", re.IGNORECASE)
SAYS_CANNOT = re.compile(r"\b(can'?t|cannot|can ?not|unable|not able|no helper can|isn'?t possible|not possible)\b", re.IGNORECASE)
HANGUL = re.compile(r"[가-힣]")
# What the person says to go on when the script has nothing more to tell: plain agreement.
AGREE = ("yes", "yes thats right", "ok")
AGREE_KO = ("네", "네 맞아요", "좋아요")
LANDS_SECONDS = 120  # how long a file that landed is waited for; a first one waits for the built-in model to load
ROOM_SHARE = 0.8  # the most of a local design model's room (DESIGN_CONTEXT) its fullest form may hold: Play.check_whole


def claims_done(words: str) -> bool:
    """Whether a line says the helper exists or runs now, not what it will do once it does."""
    return any(not ABOUT_LATER.search(words[:match.start()]) for match in SAYS_DONE.finditer(words))


def folder_like(folders: list[str], word: str) -> str:
    """The folder among these whose name has this word in it, or ""."""
    return next((folder for folder in folders if word.casefold() in folder.casefold()), "")


def as_wanted(choice: str, word: str) -> bool:
    """Whether a file came out where the person wants it: in a folder with that word in its
    name, or ("") left where it was."""
    return (not choice) if not word else word.casefold() in (choice or "").casefold()


def first_wrong(rows: list[dict], wants: dict[str, str]) -> str:
    """The first file of a try-out that came out otherwise than the person wants, or ""."""
    came = {row.get("name"): str(row.get("choice") or "") for row in rows if isinstance(row, dict)}
    return next((name for name, word in wants.items() if name in came and not as_wanted(came[name], word)), "")


def card_in(events: list) -> AgentCard | None:
    return next((event for event in reversed(events) if isinstance(event, AgentCard)), None)


def question_in(events: list) -> Question | None:
    return next((event for event in reversed(events) if isinstance(event, Question)), None)


def result_in(events: list, agent: str = "") -> Result | None:
    return next((event for event in reversed(events) if isinstance(event, Result) and (not agent or event.agent == agent)), None)


def ends_asking(events: list, id: str) -> bool:
    """Whether the last thing an answer puts on the screen is the question with this id,
    with two buttons: whatever else was said came before it."""
    drawn = [event for event in events if isinstance(event, (NoirText, Question, Result, AgentCard, Error))]
    return bool(drawn) and isinstance(drawn[-1], Question) and drawn[-1].id == id and len(drawn[-1].choices or []) == 2


def words_in(events: list) -> str:
    """Everything said in one answer, as one piece of text."""
    return " ".join(event.text for event in events if isinstance(event, (NoirText, Result, Question)))


def card_memory() -> int | None:
    """What is on the graphics card right now, in MiB, by nvidia-smi; None where there is none."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return int(out.strip().splitlines()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


# ---------------------------------------------------------------- made-up files


def pdf(path: Path, lines: list[str]) -> None:
    """A one-page PDF with these lines, the kind pypdf reads back as text."""
    content = ["BT", "/F1 11 Tf", "50 750 Td", "14 TL"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content.append(f"({safe}) Tj T*")
    content.append("ET")
    stream = "\n".join(content).encode("cp1252", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    write_pdf(path, objects)


def scan(path: Path, lines: list[str]) -> None:
    """A scanned page: one big photo of the lines, with no text behind it, the kind a
    phone or a copier makes."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (2550, 3300), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 96)
    except OSError:
        font = ImageFont.load_default()
    for number, line in enumerate(lines):
        draw.text((160, 240 + number * 180), line, fill="black", font=font)
    photo_bytes = io.BytesIO()
    image.save(photo_bytes, "JPEG", quality=80)
    jpeg = photo_bytes.getvalue()
    content = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /XObject << /Im1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        (b"<< /Type /XObject /Subtype /Image /Width 2550 /Height 3300 /ColorSpace /DeviceRGB /BitsPerComponent 8 "
         b"/Filter /DCTDecode /Length " + str(len(jpeg)).encode() + b" >>\nstream\n" + jpeg + b"\nendstream"),
    ]
    write_pdf(path, objects)


def write_pdf(path: Path, objects: list[bytes]) -> None:
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def sheet(path: Path, lines: list[str]) -> None:
    """A spreadsheet with these words, the way Excel saves one: a zip of XML."""
    import zipfile

    with zipfile.ZipFile(path, "w") as inside:
        inside.writestr("[Content_Types].xml", "<Types/>")
        inside.writestr("xl/sharedStrings.xml", "<sst>" + "".join(f"<si><t>{line}</t></si>" for line in lines) + "</sst>")
        inside.writestr("xl/worksheets/sheet1.xml", "<worksheet><sheetData/></worksheet>")


def slides(path: Path, lines: list[str]) -> None:
    import zipfile

    with zipfile.ZipFile(path, "w") as inside:
        inside.writestr("[Content_Types].xml", "<Types/>")
        inside.writestr("ppt/slides/slide1.xml", "<p:sld>" + "".join(f"<a:t>{line}</a:t>" for line in lines) + "</p:sld>")


def picture(path: Path, lines: list[str]) -> None:
    """A photo or a screenshot with writing in it: these lines drawn large on a white page."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (900, 120 + 70 * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    for number, line in enumerate(lines):
        draw.text((40, 40 + number * 70), line, fill="black", font=font)
    image.save(path)


def photo(path: Path, sky: tuple[int, int, int], ground: tuple[int, int, int]) -> None:
    """A photo with no writing in it: a sky, a sun, a hill and some ground."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1200, 800), sky)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 520, 1200, 800), fill=ground)
    draw.ellipse((860, 110, 1010, 260), fill=(255, 214, 120))
    draw.polygon([(150, 520), (420, 260), (700, 520)], fill=(90, 96, 110))
    image.save(path, quality=85)


def packed(path: Path, names: list[str]) -> None:
    import zipfile

    with zipfile.ZipFile(path, "w") as inside:
        for name in names:
            inside.writestr(name, b"x")


def word(path: Path, lines: list[str]) -> None:
    import docx

    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    document.save(str(path))


def drop(folder: Path, files: dict, start: float | None = None, step: float = 60.0) -> None:
    """Put these made-up files in a folder, each as the kind of file its name says. With
    `start`, in order and each `step` seconds newer than the one before, so which ones are
    the newest is known; without it they are new this moment, like a download."""
    folder.mkdir(parents=True, exist_ok=True)
    for number, (name, lines) in enumerate(files.items()):
        path = folder / name
        lower = name.lower()
        if lower.startswith("scan_") and lower.endswith(".pdf"):
            scan(path, lines)
        elif lower.endswith(".pdf"):
            pdf(path, lines)
        elif lower.endswith(".docx"):
            word(path, lines)
        elif lower.endswith(".ipynb"):
            path.write_text(json.dumps(lines), encoding="utf-8")
        elif lower.endswith(".xlsx"):
            sheet(path, lines)
        elif lower.endswith(".pptx"):
            slides(path, lines)
        elif lower.endswith((".png", ".jpg")) and isinstance(lines, tuple):
            photo(path, *lines)
        elif lower.endswith((".png", ".jpg")):
            picture(path, lines)
        elif lower.endswith(".zip"):
            packed(path, lines)
        elif lines is None:
            path.write_bytes(bytes(range(256)) * 64)  # a program or a recording: nothing to read
        else:
            path.write_text("\n".join(lines), encoding="utf-8")
        if start is not None:
            when = start + number * step
            os.utime(path, (when, when))


def aged(folder: Path, files: dict, days: float = 0.0) -> None:
    """These files in a folder as they would be after a while: the last one written
    `days` days and five minutes ago, each one before it a minute older."""
    drop(folder, files, start=time.time() - days * 86400 - 60 * (len(files) + 5))


# ---------------------------------------------------------------- the made-up home


class Home:
    """A temporary folder that stands in for the user's home, and one beside it for the
    app's data. Between `move_in` and `leave` the app sees these and nothing of the
    real computer."""

    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.downloads = self.home / "Downloads"
        self.desktop = self.home / "OneDrive" / "바탕 화면"  # a Korean Windows with OneDrive backup, like the user's
        self.documents = self.home / "Documents"
        self.pictures = self.home / "Pictures"
        self.appdata = root / "appdata"
        for folder in (self.downloads, self.desktop, self.documents, self.pictures, self.appdata):
            folder.mkdir(parents=True)
        self._env: dict[str, str | None] = {}
        self._swapped: list[tuple] = []

    def place(self, name: str, home: Path | None = None) -> Path:
        """Where a folder people name is here: what places.known_folder answers on the real computer."""
        if name == "home":
            return self.home
        return {"Desktop": self.desktop, "Downloads": self.downloads}.get(name, self.home / name)

    def outside(self, folder: Path) -> bool:
        """Whether a folder is not in the made-up home. It stands in for the check on system
        folders, which would refuse the home itself (a temporary folder is under AppData),
        and it keeps a run that goes wrong from being given a folder of the user's."""
        return not Path(folder).resolve().is_relative_to(self.home.resolve())

    def move_in(self) -> None:
        """Make this the home and the data folder the app sees, until `leave`."""
        # A program started from here is handed these too, so one that keeps its sign-in in
        # the home folder finds none in this one.
        for name, folder in (("LOCALAPPDATA", self.appdata), ("XDG_DATA_HOME", self.appdata),
                             ("USERPROFILE", self.home), ("HOME", self.home)):
            self._env.setdefault(name, os.environ.get(name))
            os.environ[name] = str(folder)
        self._swap("known_folder", self.place)
        self._swap("is_blocked", self.outside)
        taken = all(module.known_folder == self.place for module in ASK_FOR_PLACES)
        if not taken or not noir.data_dir().is_relative_to(self.root) or Path.home() != self.home:
            self.leave()
            raise RuntimeError("The made-up home did not take, so nothing was started: a run must never reach "
                               "the user's own folders.")

    def leave(self) -> None:
        """Put back what `move_in` replaced."""
        for module, name, was in reversed(self._swapped):
            setattr(module, name, was)
        self._swapped = []
        for name, was in self._env.items():
            if was is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = was
        self._env = {}

    def _swap(self, name: str, ours) -> None:
        """Replace `name` in every module of the app that has it, whichever modules they
        are: one that says `from ..places import known_folder` holds a reference of its own,
        which replacing the one in places.py does not reach."""
        for key, module in list(sys.modules.items()):
            if module is not None and (key == "concierge" or key.startswith("concierge.")) and name in vars(module):
                self._swapped.append((module, name, vars(module)[name]))
                setattr(module, name, ours)

    def short(self, text: str) -> str:
        """A line as it is printed: the long temporary path as ~."""
        return text.replace(str(self.home), "~")


class Run:
    """One run: the made-up home, every word printed the way the window would show it,
    and the checks."""

    def __init__(self, root: Path):
        self.home = Home(root)
        self.checks: list[bool] = []
        self.failed: list[str] = []  # what each check that did not hold was about
        self.said: list[str] = []  # what Noir said in the conversation running now

    def show(self, events, label: str) -> list:
        """Print what came back for one thing the user typed or clicked, and keep it."""
        print(f"\n  USER  {label}")
        kept, text = [], []
        for event in events:
            kept.append(event)
            if isinstance(event, NoirText):
                text.append(event.text)
                continue
            if text:
                self.spoke("".join(text))
                text = []
            if isinstance(event, Thinking):
                print("        [think]", self.home.short(event.text.strip().replace("\n", " ")))
            elif isinstance(event, Question):
                self.spoke(event.text, f"  {event.choices or ''}")
            elif isinstance(event, AgentCard):
                print(f"        CARD {event.name} ({event.kind})")
                for line in (*event.reads, *event.can_do, *(f"never: {line}" for line in event.cannot_do)):
                    print("          -", self.home.short(line))
                print(f"          runs on {event.runs_on}; buttons {event.actions}")
            elif isinstance(event, Result):
                print(f"        RESULT ({event.agent}):")
                for line in self.home.short(event.text).splitlines():
                    print("          " + line)
                for source in event.sources or []:
                    print(f"          (from {self.home.short(source.path)}: {source.quote[:160]!r})")
            elif isinstance(event, Progress):
                print("        (progress)", self.home.short(event.text))
            elif isinstance(event, AgentList):
                print(f"        (helpers: {event.agents}; switched on: {event.active})")
            elif isinstance(event, Error):
                print("        ERROR:", event.text)
        if text:
            self.spoke("".join(text))
        return kept

    def spoke(self, words: str, more: str = "") -> None:
        words = self.home.short(words.strip())
        self.said.append(words)
        print(f"  NOIR  {words}{more}")

    def check(self, condition: bool, what: str) -> None:
        print(("  OK    " if condition else "  FAIL  ") + what)
        self.checks.append(bool(condition))
        if not condition:
            self.failed.append(what)


# ---------------------------------------------------------------- the real models, counted


class Counted(Ollama):
    """The real Ollama, which also keeps what each thing asked of a model took: which
    model, how long, the tokens it read and wrote (Ollama's own count), which models were
    in memory right after, and for a form, the form."""

    def __init__(self):
        super().__init__()
        self.calls: list[dict] = []

    def chat_json(self, model, messages, schema, think=None, keep_alive=None, options=None):
        started, filled = time.monotonic(), None
        try:
            filled = super().chat_json(model, messages, schema, think=think, keep_alive=keep_alive, options=options)
            return filled
        finally:
            self._keep(model, started, messages, filled)

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        started = time.monotonic()
        try:
            yield from super().chat(model, messages, think=think, options=options, keep_alive=keep_alive)
        finally:
            self._keep(model, started, messages, None)

    def chat_parts(self, model, messages, think=None, options=None, keep_alive=None):
        started = time.monotonic()
        try:
            yield from super().chat_parts(model, messages, think=think, options=options, keep_alive=keep_alive)
        finally:
            self._keep(model, started, messages, None)

    def _keep(self, model: str, started: float, messages: list[dict], form: dict | None) -> None:
        read, wrote = self.last_tokens
        try:
            loaded = sorted(one["name"] for one in self.loaded())
        except Exception:  # noqa: BLE001 - Ollama busy: this one is not known
            loaded = []
        note = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
        self.calls.append({"model": model, "seconds": time.monotonic() - started, "read": read, "wrote": wrote,
                           "loaded": loaded, "form": form, "note": note})


class NoWatcher:
    """Stands where the mouse watcher would be. The eval never listens to the real mouse:
    with the real one, a helper switched on here would read whatever the user highlights
    in any program while the eval runs, and show bubbles on their screen."""

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class Bubbles:
    """Stands where the bubble on the screen would be: what would be shown is kept."""

    def __init__(self):
        self.shown: list[tuple[str, str]] = []  # (the bubble's title, its text)

    def show(self, text, rect, title="", seconds=None, stay=False) -> None:
        self.shown.append((title, text))

    def pressed(self, x, y) -> None:
        pass

    def hide(self) -> None:
        pass

    def close(self) -> None:
        pass


class RealHome:
    """Stands where `subprocess` is in accounts.py while a plan's app is used: the app is
    started with the home folder the user really has, where it keeps its sign-in. The
    eval's own process keeps the made-up one all the while."""

    def __init__(self, env: dict):
        self._env = env

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def Popen(self, *args, **more):  # noqa: N802 - the name accounts.py calls
        return subprocess.Popen(*args, env=self._env, **more)

    def run(self, *args, **more):
        return subprocess.run(*args, env=self._env, **more)


# ---------------------------------------------------------------- one conversation


class Talk(Run):
    """One conversation: a made-up person on a home of their own, the real engine on it,
    and what each turn took."""

    def __init__(self, play: "Play", name: str, title: str):
        super().__init__(play.root / name)
        self.play, self.name, self.title = play, name, title
        self.engine: NoirEngine | None = None
        self.ollama: Counted | None = None
        self.design_tag = ""  # the design model's tag in Ollama; "" for a plan's model
        self.turns: list[dict] = []
        # What the windows are told from the thread that watches folders, kept as they would get it.
        self.moves: list[dict] = []
        self.stays: list[dict] = []
        self.bubbles = Bubbles()
        self.copied: list[str] = []
        # What Noir said in the turns after which a helper was still being worked out: the
        # lines held to "never says it is on or made". (An answer to something else in the
        # middle is not one of them, nor what is said once the button was pressed.)
        self.worked_out: list[str] = []
        self._quick_was = None
        self._seeds: set[str] = set()

    # ------------------------------------------------------------ plumbing

    def open(self, build, seeds: tuple = ()) -> Home | None:
        """Move into the made-up home, put the person's files there, and start the real
        engine on it. None when it could not be started (said, and counted as a failed check)."""
        home = self.home
        home.move_in()
        build(home)
        for agent in seeds:
            store.save(agent)
            self._seeds.add(agent.name)
        # The engine makes what reads highlights by this name. Here it gets one that never
        # touches the mouse, the screen or the clipboard.
        self._quick_was = engine_mod.QuickAgents
        engine_mod.QuickAgents = self._pretend_quick
        self.ollama = Counted()
        if self.play.plan is not None:
            self.play.plan.calls = self.ollama.calls  # what each of its turns took is kept with the rest
        self.engine = NoirEngine(self.ollama)
        problems = [event.text for event in self.engine.startup() if isinstance(event, Error)]
        if problems or self.engine.designer is None:
            print("  Noir isn't running:", "; ".join(problems))
            self.check(False, "the engine started")
            return None
        watch = self.engine.folderwatch
        watch.moved, watch.stayed = self.moves.append, self.stays.append
        if self.play.plan is not None:
            # The designer was handed the engine's way of choosing when the engine started,
            # so the plan goes to the designer itself. Set on the engine alone, it was never
            # asked: a play "through the plan" was talked through by the local model, and the
            # line above the conversation named the plan's model all the same.
            self.engine._design_model = self.engine.designer.design_model = self.play.plan.model
        elif self.play.tag:
            entry = ModelEntry(tag=self.play.tag, name=nice_name(self.play.tag), download_gb=0, memory_gb=0, measured=False,
                               languages=[])
            self.engine._local_designer = lambda: entry
        # Asked of the designer, which is what talks: the line says who really designs.
        model = self.engine.designer.design_model()
        if model is None:
            print("  Nobody can design on this computer: no model on the designers list (models.yaml) is installed "
                  "and fits. Name a tag to try one.")
            self.check(False, "a model can design")
            return None
        if model.here:
            self.design_tag = self.play.tag or self.engine._local_designer().tag
        self.play.designer_name = model.name
        print(f"  (design model: {model.name}, {'on this computer' if model.here else 'off this computer'}; "
              f"on the graphics card now: {card_memory()} MiB)")
        return home

    def _pretend_quick(self, ollama, model, think) -> QuickAgents:
        return QuickAgents(ollama, model, think, make_watcher=lambda *args: NoWatcher(), make_bubble=lambda: self.bubbles,
                           set_clipboard=self.copied.append, highlighted=lambda: "")

    def close(self) -> None:
        """End the conversation: the engine closed, its threads done, the models out of the
        graphics memory, and only then the made-up home left."""
        try:
            if self.engine is not None:
                self.engine.close()
                thread = self.engine.folderwatch._thread
                if thread is not None:
                    thread.join(timeout=60)
                if self.ollama is not None:
                    for tag in (self.design_tag, noir.NOIR_MODEL):
                        try:
                            if tag:
                                self.ollama.unload(tag)
                        except Exception:  # noqa: BLE001 - not loaded, or Ollama stopped
                            pass
        finally:
            if self._quick_was is not None:
                engine_mod.QuickAgents = self._quick_was
            self.home.leave()

    def say(self, text: str) -> list:
        return self._step(self.engine.send(text), text)

    def click(self, id: str, choice: str) -> list:
        return self._step(self.engine.choose(id, choice), f"[clicks {choice}]")

    def _step(self, events, label: str) -> list:
        """One thing typed or clicked: every word of the answer printed, and what it took."""
        mark, started, said = len(self.ollama.calls), time.monotonic(), len(self.said)
        kept = self.show(events, label)
        seconds = time.monotonic() - started
        if self.designing():
            self.worked_out += self.said[said:]
        calls = self.ollama.calls[mark:]
        forms = [call for call in calls if call["model"] == (self.design_tag or "plan")]
        others = [call for call in calls if call not in forms]
        turn = {"label": label, "seconds": seconds, "forms": forms, "others": len(others), "card": card_memory(),
                "loaded": self._loaded()}
        self.turns.append(turn)
        line = f"        [turn] {seconds:.1f} s"
        if forms:
            each = "; ".join(f"{call['seconds']:.1f} s, read {call['read']:,}, wrote {call['wrote']:,}" for call in forms)
            line += f" · {self.play.designer_name} filled {len(forms)} form{'' if len(forms) == 1 else 's'} ({each})"
        if others:
            line += f" · the built-in model was asked {len(others)} time{'' if len(others) == 1 else 's'}"
        print(f"{line} · on the graphics card: {turn['card']} MiB, in memory: {', '.join(turn['loaded']) or 'nothing'}")
        if self.play.forms:
            for call in forms:
                self._show_form(call)
        return kept

    def _show_form(self, call: dict) -> None:
        """One form the design model filled, without its empty fields, and what code had told it."""
        told = call["note"].split("PROBLEMS WITH YOUR LAST FORM", 1)
        if len(told) == 2:
            for line in told[1].split("\n\nFORM NOTE", 1)[0].strip().splitlines()[1:]:
                print("        [code told the model]", line)
        form = call["form"] if isinstance(call["form"], dict) else {}
        kept = {key: value for key, value in form.items() if value not in ("", None, {"place": "", "name": ""})}
        print("        [form]", self.home.short(json.dumps(kept, ensure_ascii=False)))

    def _loaded(self) -> list[str]:
        try:
            return sorted(one["name"] for one in self.ollama.loaded())
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------ how things stand

    def sketch(self):
        return self.engine.designer.sketch

    def designing(self) -> bool:
        return self.engine.designer.active

    def card_up(self) -> bool:
        """Whether the card on the screen is the card as it now stands."""
        sketch = self.sketch()
        return sketch is not None and sketch.shown is not None and sketch.shown == sketch.slots

    def slots(self) -> dict:
        return dict(self.sketch().slots) if self.sketch() is not None else {}

    def last_asks(self) -> str:
        """The setting the design model's last whole form said its question asks for; ""
        when it said none, or filled no whole form yet."""
        forms = [call["form"] for call in self.ollama.calls if isinstance(call["form"], dict) and "asks" in call["form"]]
        return str(forms[-1].get("asks") or "") if forms else ""

    def made(self) -> list[store.Agent]:
        """The helpers saved in this conversation: not the ones it began with."""
        return [agent for agent in store.list_agents() if agent.name not in self._seeds]

    @staticmethod
    def names(folder: Path) -> set[str]:
        """What is loose in a folder right now."""
        return {path.name for path in folder.iterdir() if path.is_file()}

    # ------------------------------------------------------------ the person's side

    def work_out(self, events: list, lines: tuple = (), agree: tuple = AGREE) -> list:
        """Say these lines one after the other, and plain agreement after them, until the
        card is on the screen as it stands or the conversation is over: the design model
        may take a turn more or fewer to get there. Returns the last answer."""
        for line in (*lines, *agree):
            if self.card_up() or not self.designing():
                break
            events = self.say(line)
        return events

    def create(self, yes: str = "") -> list:
        """Make what the card shows: by a typed yes when one is given, and by the card's
        button when there is none or the yes answered a question of Noir's instead."""
        events: list = []
        if yes:
            events = self.say(yes)
        if self.designing() and self.card_up():
            if yes:
                print("        (the typed yes did not make it, so the card's button is pressed)")
            events = self.click(CARD, SAVE_CHANGES if self.sketch().editing else CREATE_IT)
        return events

    def before_the_button(self, folder: Path | None = None, before: set[str] | None = None) -> None:
        """What holds for every conversation up to the card's button: Noir never says the
        helper is on or made, nothing is saved, and no file has moved."""
        claims = [words for words in self.worked_out if claims_done(words)]
        self.check(not claims, "it never says the helper is on or made before the button" + (f": {claims[0][:140]}" if claims else ""))
        self.check(not self.made(), "nothing is made by talking")
        if folder is not None:
            self.check(self.names(folder) == before, f"no file in {folder.name} has moved")

    def lands(self, folder: Path, files: dict, watcher: str) -> dict:
        """New files land in a watched folder, as downloads do, and the helper that watches
        is waited for: what the windows were told meanwhile is printed and returned,
        {"lines": what the chores list said it was doing, "moved": [...], "stayed": [...]}."""
        watch = self.engine.folderwatch
        moves, stays, lines = len(self.moves), len(self.stays), []
        print(f"\n  (new in {folder.name}: {', '.join(files)})")
        drop(folder, files)
        waiting, deadline = set(files), time.monotonic() + LANDS_SECONDS
        while waiting and time.monotonic() < deadline:
            for row in self.engine.chore_agents():
                if row["name"] == watcher and row.get("now") and row["now"] not in lines:
                    lines.append(row["now"])
                    print("        (its line in the chores list)", row["now"])
            dealt = {move["name"] for move in self.moves[moves:]} | {item["name"] for item in watch.skipped.get(watcher, [])}
            waiting -= dealt
            time.sleep(0.1)
        time.sleep(0.3)  # the record is written right after the windows are told
        for move in self.moves[moves:]:
            print(f"        (the note by the circle) {move['text']}" + ("   [Undo] [OK]" if move.get("sort") else "   [OK]"))
            for step in move.get("steps", []):
                print("            ·", self.home.short(step))
        for stay in self.stays[stays:]:
            print(f"        (the log by the circle) {stay['name']} stayed: {stay['why']}")
            for step in stay.get("steps", []):
                print("            ·", self.home.short(step))
        if waiting:
            print(f"        (not dealt with after {LANDS_SECONDS} s: {', '.join(sorted(waiting))})")
        return {"lines": lines, "moved": self.moves[moves:], "stayed": self.stays[stays:], "waiting": waiting}

    def chores(self) -> dict:
        """The chores list as the drawer and the Chores page would draw it, printed."""
        listing = chores.listing({}, self.engine.chore_done(), self.engine.chore_agents(), [])
        print("        (the chores list)")
        for chore in listing["chores"][1:]:  # the first is the watch's own, which is not played here
            print(f"            {chore['name']} · {'on' if chore['on'] else 'off'} · {chore['how']}")
            print(f"              {self.home.short(chore['last'])}")
        for day in listing["days"]:
            for job in day["jobs"]:
                print(f"            {day['day']} {job['time']}  {self.home.short(job['text'])}" + ("   [Undo]" if job.get("undo") else ""))
        return listing

    def highlight(self, text: str) -> list[tuple[str, str]]:
        """What the mouse watcher does when text is highlighted in some program, done by
        hand: the helpers that are on get the text. Returns what the bubble showed."""
        quick = self.engine.quick
        mark = len(self.bubbles.shown)
        for name in quick.active:
            quick.last.pop(name, None)
        print(f"\n  (highlighted in another program: {text})")
        quick.highlighted(text, None)
        deadline = time.monotonic() + LANDS_SECONDS
        while time.monotonic() < deadline and not all(name in quick.last for name in quick.active):
            time.sleep(0.1)
        shown = [one for one in self.bubbles.shown[mark:] if one[1] != "Working on it..."]
        for title, words in shown:
            print(f"        (the bubble above it) [{title}] {words}")
        if not shown:
            came = ", ".join(f"{name}: {quick.last.get(name, 'nothing yet')}" for name in quick.active)
            print(f"        (no bubble; {came})")
        return shown


# ---------------------------------------------------------------- the homes


def shop_home(home: Home) -> None:
    aged(home.downloads, SHOP)
    aged(home.documents, {"supplier_contacts.txt": ["Velo Parts Wholesale: orders@veloparts.example", "Kestrel Cycles: dealer line 503 555 0118"]}, days=9)
    aged(home.desktop, {"todo.txt": ["order tubes", "call Kestrel about the Tarn frames", "renew shop insurance"]}, days=2)


def house_home(home: Home) -> None:
    aged(home.downloads, HOUSE)
    aged(home.documents / "House papers", HOUSE_PAPERS, days=3)
    aged(home.documents / "Household" / "Appliance manuals", MANUALS, days=40)
    aged(home.desktop, {"shopping list.txt": ["milk", "dog food", "printer paper"]}, days=1)
    aged(home.pictures, {"IMG_0902.jpg": ((130, 180, 240), (200, 190, 150))}, days=5)


def korean_home(home: Home) -> None:
    aged(home.downloads, KOREAN_HOME)
    aged(home.documents, {"가계부_2026.xlsx": ["가계부 2026", "월", "식비", "교육비", "1월", "620000", "310000"]}, days=6)


def hobby_home(home: Home) -> None:
    aged(home.downloads, HOBBY_DOWNLOADS)
    aged(home.pictures, HOBBY_PICTURES, days=4)
    aged(home.documents / "Bee club", {"minutes_october.docx": ["Willow Valley Beekeepers - minutes, October", "Present: 14 members",
                                                                "The honey show will be on 21 November."]}, days=20)


def mover(name: str, home: Home, folders: str, rule: str) -> store.Agent:
    """A helper that moves the new files of Downloads, as one saved earlier would be."""
    return store.Agent(name=name, blueprint=parts.CUSTOM, slots={
        "when": parts.NEW_FILE, "then": parts.MOVE, "folder": str(home.downloads), "looks_at": parts.INSIDE_FILE,
        "choices": folders, "open": parts.OPEN_NO, "into": "", "instruction": rule, "name": name})


# ---------------------------------------------------------------- the conversations


def thin(t: Talk) -> None:
    """A thin request: worked out by talking, corrected after the try-out, made by a typed yes."""
    home = t.open(shop_home)
    if home is None:
        return
    before = t.names(home.downloads)
    events = t.say("my downloads folder is a mess, can you do something about it")
    t.check(t.designing(), "the request opens a conversation about a helper")
    t.check(question_in(events) is not None and card_in(events) is None and not t.slots().get("when"),
            "a first message that only names a trouble gets one question, and nothing is proposed yet")
    events = t.say("its mostly stuff from my two parts suppliers, bills for the shop and then random things. "
                   "i can never find an invoice when i need it")
    t.check(card_in(events) is None, "no card comes before they have agreed to anything")
    events = t.work_out(events, ("each supplier gets its own folder, velo parts and kestrel cycles. bills can go together. "
                                 "leave the random things where they are",))
    slots, tried = t.slots(), result_in(events, TRY_OUT)
    t.check(t.card_up() and tried is not None, "once they have agreed, the try-out and the card come")
    t.check((slots.get("when"), slots.get("then")) == (parts.NEW_FILE, parts.MOVE) and slots.get("folder") == str(home.downloads),
            "the card works on the new files of Downloads and moves them")
    folders = parts.choices_of(slots)
    t.check(all(folder_like(folders, word) for word in ("velo", "kestrel", "bill")),
            f"its folders are the two suppliers' and one for bills: {folders}")
    t.before_the_button(home.downloads, before)
    if not t.card_up():
        return
    # Something to correct, found in the try-out itself: the first file that came out
    # otherwise than Tomás wants, or, when all came out right, one more wish.
    rows = t.sketch().tried or []
    name = first_wrong(rows, SHOP_WANTS)
    word, line = (SHOP_WANTS[name], SHOP_SAYS[name]) if name else SHOP_ALSO[1:]
    name = name or SHOP_ALSO[0]
    rule = slots.get("instruction")
    events = t.work_out(t.say(line))
    now = {row.get("name"): str(row.get("choice") or "") for row in t.sketch().tried or []} if t.designing() else {}
    t.check(t.slots().get("instruction") != rule, "the correction changed the rule")
    t.check(result_in(events, TRY_OUT) is not None and card_in(events) is not None,
            "it was tried again and the card shown again")
    t.check(name in now and as_wanted(now[name], word),
            f"after the correction {name} comes out as they asked: {now.get(name) or 'it stays'}")
    events = t.say("will it touch the stuff thats already in there?")
    t.check(card_in(events) is None and t.card_up() and bool(SAYS_STAYS.search(words_in(events))),
            "a question at the card is answered (what is there already is left alone), and the card stays as it is")
    t.before_the_button(home.downloads, before)
    events = t.create("ok great")
    made = t.made()
    t.check(len(made) == 1 and bool(str(made[0].slots.get("instruction") or "").strip()), "the helper is made, with its rule")
    if not made:
        return
    question = question_in(events)
    t.check(t.engine.folderwatch.is_on(made[0].name) and question is not None and question.id == FIRST_PASS
            and len(question.choices) == 2, "it is switched on, and asks once about the files already there")
    t.check(t.names(home.downloads) == before, "making it moved nothing")
    t.click(FIRST_PASS, ONLY_NEW)
    time.sleep(4)
    t.check(t.names(home.downloads) == before, "only new files from now on: what was there is still there")


def notes(t: Talk) -> None:
    """A few lines about each new file in a folder: asked for, corrected, made by the button, then at work."""
    home = t.open(house_home)
    if home is None:
        return
    papers = home.documents / "House papers"
    before = t.names(papers)
    events = t.work_out(t.say("whenever i save something into my House papers folder, can you write down a couple of lines "
                              "about it so i remember what it was"), ("its the one in my documents",))
    slots, tried = t.slots(), result_in(events, TRY_OUT)
    t.check(t.card_up() and tried is not None and "Nothing was written" in tried.text,
            "the try-out shows what it would write, and writes nothing")
    t.check((slots.get("when"), slots.get("then")) == (parts.NEW_FILE, parts.NOTE) and slots.get("folder") == str(papers),
            "the card writes about the new files of House papers")
    t.before_the_button(papers, before)
    if not t.card_up():
        return
    rule = slots.get("instruction")
    events = t.work_out(t.say("can it also say the date i have to do something by, when there is one"))
    again = result_in(events, TRY_OUT)
    t.check(t.slots().get("instruction") != rule and again is not None, "the change went into the rule and was tried again")
    t.check(again is not None and bool(re.search(r"\b(1 December|15 December|27 November|December 1|December 15|November 27)", again.text)),
            "the notes of the try-out now carry the dates things are due by")
    t.before_the_button(papers, before)
    events = t.create()
    made = t.made()
    t.check(len(made) == 1 and parts.then_of(made[0].slots) == parts.NOTE, "the button makes the helper")
    if not made:
        return
    agent = made[0]
    file = parts.notes_path(agent.slots)
    question = question_in(events)
    t.check(question is not None and question.id == FIRST_PASS and not file.exists(), "it asks about the papers already there, and has written nothing yet")
    events = t.click(FIRST_PASS, GO_THROUGH)
    written = file.read_text(encoding="utf-8") if file.is_file() else ""
    t.check(sum(name in written for name in HOUSE_PAPERS) >= 4, f"the first pass wrote about the papers in {file.name}")
    t.check(t.names(papers) - {file.name} == before, "and every paper is still where it was")
    print("        (the notes file now)")
    for line in written.splitlines():
        print("            " + line)
    landed = t.lands(papers, HOUSE_PAPERS_LATER, agent.name)
    name = next(iter(HOUSE_PAPERS_LATER))
    told = next((move for move in landed["moved"] if move["name"] == name), None)
    t.check(any(name in line for line in landed["lines"]), "while the new paper is read, the chores list says so")
    t.check(told is not None and told["text"] == f"Wrote about {name} in {file.name}" and not told["sort"],
            "the windows are told a note was written (nothing to undo)")
    t.check(name in file.read_text(encoding="utf-8") and (papers / name).is_file(), "the note is in the notes file, and the paper was not touched")
    listing = t.chores()
    row = next((chore for chore in listing["chores"] if chore["name"] == agent.name), {})
    t.check(str(row.get("last", "")).startswith(f"Wrote about {name}"), "its line in the chores list says what it last wrote about")


def highlight(t: Talk) -> None:
    """A helper for highlighted text that turns it into one language, made, used, then changed to another."""
    home = t.open(hobby_home)
    if home is None:
        return
    events = t.work_out(t.say("im learning japanese. when i highlight a japanese sentence i want to see what it means in english"))
    slots, tried = t.slots(), result_in(events, TRY_OUT)
    t.check(t.card_up() and tried is not None, "the try-out and the card come")
    t.check((slots.get("when"), slots.get("then")) == (parts.WHILE_ON, parts.SHOW), "the card works on highlighted text and shows the result there")
    t.check(slots.get("skip_language") == "English", f"it leaves out text that is already in English: {slots.get('skip_language')!r}")
    t.before_the_button()
    if not t.card_up():
        return
    rule = slots.get("instruction")
    events = t.say("what would it give for 今日は忙しかったけど、楽しかったです")
    tried = result_in(events, TRY_OUT)
    t.check(tried is not None and "今日は忙しかった" in tried.text and t.slots().get("instruction") == rule,
            "their own text is tried, and the card stays as it was")
    events = t.create()
    made = t.made()
    t.check(len(made) == 1 and t.engine.quick is not None and t.engine.quick.is_on(made[0].name), "the button makes it and switches it on")
    if not made or t.engine.quick is None:
        return
    name = made[0].name
    shown = t.highlight("明日の会議は三時からです。")
    t.check(t.engine.quick.last.get(name) == ANSWERED and bool(shown) and not HANGUL.search(shown[-1][1]),
            "a Japanese sentence highlighted in another program gets its meaning in a bubble")
    shown = t.highlight("The meeting starts at three tomorrow.")
    t.check(t.engine.quick.last.get(name) == LEFT_OUT and not shown, "an English sentence is left out: nothing is shown for it")
    # Changed to another language by talking: the setting has to follow the rule.
    events = t.work_out(t.say(f"change {name} so it tells me the meaning in korean instead of english"))
    slots = t.slots()
    t.check(t.designing() and t.sketch().editing and t.card_up(), "a change to it is talked through, and ends in a card")
    t.check(slots.get("skip_language") == "Korean", f"the language it leaves out follows the rule: {slots.get('skip_language')!r}")
    t.check(store.find_agent(name) is not None and store.find_agent(name).slots.get("instruction") == rule,
            "the helper they have is as it was until they save")
    t.create("save it")
    saved = next(iter(t.made()), None)
    t.check(saved is not None and saved.slots.get("instruction") != rule and len(t.made()) == 1, "saving changes the one helper")
    if saved is None:
        return
    shown = t.highlight("明日の会議は三時からです。")
    t.check(bool(shown) and bool(HANGUL.search(shown[-1][1])), "and from then on the bubble is in Korean")


def chat(t: Talk) -> None:
    """A helper that is asked in the chat: made, then asked by its name."""
    home = t.open(hobby_home)
    if home is None:
        return
    events = t.say("after every hive inspection i type rough notes on my phone. i want something that turns them into "
                   "a tidy entry for my hive log")
    events = t.work_out(events, ("in the chat is fine",))
    slots, tried = t.slots(), result_in(events, TRY_OUT)
    name = str(slots.get("name") or "")
    t.check(t.card_up() and tried is not None, "the try-out and the card come")
    t.check((slots.get("when"), slots.get("then")) == (parts.IN_CHAT, parts.ANSWER), "the card is asked in the chat and answers there")
    t.check(bool(name) and any(name.casefold() in words.casefold() for words in t.said),
            "before the card, they were told it is asked by its name")
    t.before_the_button()
    if not t.card_up():
        return
    events = t.create("great thanks")
    made = t.made()
    t.check(len(made) == 1 and made[0].name == name, "it is made")
    if not made:
        return
    t.check(f'"{name}:' in words_in(events), "and it says how to ask it")
    events = t.say(f"{name}: hive 3 - queen seen, 6 frames brood, 2 of stores, calm. added a super. 2 wasps at the "
                   "entrance. next check in 10 days")
    answer = result_in(events, name)
    t.check(answer is not None and "queen" in answer.text.lower() and len(answer.text) > 60,
            "asked by its name, it does its job on the text and answers in the chat")


def documents(t: Talk) -> None:
    """Questions about a folder of documents: the folder found though its name was typed wrong, made, then asked."""
    home = t.open(house_home)
    if home is None:
        return
    manuals = home.documents / "Household" / "Appliance manuals"
    events = t.say("i want to be able to ask questions about the manuals for the things in our house")
    if t.designing() and not t.card_up():
        # The name is typed one letter wrong. Code asks about the folder that is there by
        # its real name; the design model may also have read past the slip itself. Either
        # way they are told which folder it took them to mean and asked, before any card.
        events = t.say("theyre in my applience manuals folder")
        t.check("appliance manuals" in words_in(events).lower() and "?" in words_in(events) and card_in(events) is None,
                "a folder name typed one letter wrong: the folder that is there is said back by its real name, and "
                "they are asked before any card comes")
    events = t.work_out(events, ("yes that one",))
    slots = t.slots()
    tried = result_in(events, TRY_OUT)
    t.check(t.card_up() and slots.get("then") == parts.DOCUMENTS and slots.get("folder") == str(manuals),
            "the card answers from the documents in Appliance manuals")
    t.check(tried is not None and "5 files" in tried.text, "it says how many files it can read there")
    t.before_the_button(manuals, set(MANUALS))
    if not t.card_up():
        return
    events = t.create()
    made = t.made()
    t.check(len(made) == 1 and made[0].blueprint == parts.DOCUMENTS_QA, "the button makes it")
    if not made:
        return
    events = t.say(f"{made[0].name}: how do i top up the boiler pressure?")
    answer = result_in(events, made[0].name)
    t.check(answer is not None and any("boiler_quick_guide.pdf" in source.path for source in answer.sources or []),
            "asked about the boiler, it answers from the boiler's guide and says so")
    t.check(t.names(manuals) == set(MANUALS), "and the manuals are untouched")


def cannot(t: Talk) -> None:
    """Something no helper can do: said honestly, at once, and nothing is made."""
    home = t.open(hobby_home)
    if home is None:
        return
    events = t.say("can you make something that reads my email every morning and tells me which ones are important")
    t.check(card_in(events) is None and not t.made(), "no card comes and nothing is made")
    t.check(bool(SAYS_CANNOT.search(words_in(events))), "it says plainly that this can't be done")
    t.check(not t.designing(), "the conversation ends there, in one turn")
    t.check(len(planner.list_ideas()) == 1 and "kept the idea" in words_in(events), "the wish is kept in the ideas list, and it says so")
    claims = [words for words in t.said if claims_done(words)]
    t.check(not claims, "it never says anything is on or made")


def korean(t: Talk) -> None:
    """A whole conversation in Korean, on files that are mostly Korean."""
    home = t.open(korean_home)
    if home is None:
        return
    before = t.names(home.downloads)
    events = t.say("다운로드 폴더가 너무 지저분해요. 좀 정리해 줄 수 있어요?")
    t.check(t.designing() and question_in(events) is not None and bool(HANGUL.search(question_in(events).text)),
            "the request opens the conversation, and the first question is in Korean")
    events = t.say("주로 아이 학교에서 온 안내문이랑 공과금 고지서예요. 나머지는 이것저것이고요.")
    events = t.work_out(events, ("학교에서 온 건 '학교' 폴더에, 고지서는 '고지서' 폴더에 넣어 주세요. 나머지는 그대로 두세요.",), AGREE_KO)
    slots = t.slots()
    folders = parts.choices_of(slots)
    t.check(t.card_up() and result_in(events, TRY_OUT) is not None, "the try-out and the card come")
    t.check(all(HANGUL.search(words) for words in t.said), "every line of the conversation is in Korean")
    t.check(slots.get("folder") == str(home.downloads) and all(folder_like(folders, word) for word in ("학교", "고지서")),
            f"it watches Downloads, and its folders are the two they named: {folders}")
    rows = {row.get("name"): str(row.get("choice") or "") for row in (t.sketch().tried or [])} if t.designing() else {}
    right = [name for name, word in KOREAN_WANTS.items() if name in rows and as_wanted(rows[name], word)]
    t.check(len(right) >= len([name for name in KOREAN_WANTS if name in rows]) - 1 and len(rows) >= 6,
            f"the rule, written for the built-in model, is followed on their files: {len(right)} of "
            f"{len([name for name in KOREAN_WANTS if name in rows])} as they want")
    t.before_the_button(home.downloads, before)
    if not t.card_up():
        return
    t.create("네 좋아요")
    made = t.made()
    t.check(len(made) == 1 and bool(HANGUL.search(str(made[0].slots.get("instruction")))), "it is made, with a rule in Korean")


def at_once(t: Talk) -> None:
    """Everything said in one message, a change at the card, then the helper's life once it is made."""
    home = t.open(shop_home)
    if home is None:
        return
    before = t.names(home.downloads)
    events = t.say("can you watch my downloads folder and put anything from my suppliers, velo parts or kestrel cycles, "
                   "into a folder called Suppliers, and bills the shop has to pay into a folder called Bills. leave "
                   "everything else where it is. keep those two folders in a folder called Shop papers on my desktop")
    # Everything was in that one message. The design model may still say it back and ask
    # whether that is right, or ask one thing more; what it may not do is ask for something
    # the message said, or take more than one answer of theirs to get to the card.
    first_card, asked = card_in(events) is not None, t.last_asks()
    events = t.work_out(events)
    slots = t.slots()
    t.check(first_card or asked not in ("folder", "choices", "into", "instruction"),
            "nothing the one message said is asked for again" + ("" if first_card else f" (its question was about: {asked or 'no setting'})"))
    t.check(len(t.turns) <= 2 and result_in(events, TRY_OUT) is not None, "the try-out and the card come by the second answer")
    t.check(slots.get("folder") == str(home.downloads), "it watches Downloads, not the place its folders are kept")
    t.check(slots.get("into") == str(home.desktop / "Shop papers"), f"its folders are kept in Shop papers on the desktop: {home.short(str(slots.get('into')))}")
    t.check(sorted(name.casefold() for name in parts.choices_of(slots)) == ["bills", "suppliers"],
            f"its folders are Suppliers and Bills: {parts.choices_of(slots)}")
    t.before_the_button(home.downloads, before)
    if not t.card_up():
        return
    # When the try-out shows something going where he doesn't want it, he says so. (What
    # a supplier sends is also something to pay: said once in one message, the two are
    # easy to take for one another, and only the try-out shows it.)
    wrong = first_wrong(t.sketch().tried or [], SHOP_WANTS_TWO)
    if wrong:
        rule = slots.get("instruction")
        events = t.work_out(t.say(SHOP_SAYS_TWO[SHOP_WANTS_TWO[wrong]]))
        now = {row.get("name"): str(row.get("choice") or "") for row in t.sketch().tried or []} if t.designing() else {}
        t.check(t.slots().get("instruction") != rule and result_in(events, TRY_OUT) is not None,
                "what the try-out got wrong is corrected: the rule changes and it is tried again")
        t.check(wrong in now and as_wanted(now[wrong], SHOP_WANTS_TWO[wrong]),
                f"after the correction {wrong} comes out as they asked: {now.get(wrong) or 'it stays'}")
        t.before_the_button(home.downloads, before)
    else:
        print("        (the first try-out put everything where he wants it: nothing to correct)")
    if not t.card_up():
        return
    events = t.say("ok but call it Paper sorter")
    t.check(not t.made(), '"ok but ..." is a change, not a yes')
    t.check(t.slots().get("name") == "Paper sorter" and result_in(events, TRY_OUT) is None,
            "the name changes, and it is not tried again for a name")
    events = t.create()
    made = t.made()
    t.check(len(made) == 1 and made[0].name == "Paper sorter", "the button makes it")
    if not made:
        return
    name, papers, watch = made[0].name, home.desktop / "Shop papers", t.engine.folderwatch
    listed = next((event for event in reversed(events) if isinstance(event, AgentList)), None)
    t.check(listed is not None and name in listed.active and watch.is_on(name), "it is switched on")
    t.check(t.names(home.downloads) == before and not papers.exists(), "making it moved nothing")

    # The first pass over what is there already.
    events = t.click(FIRST_PASS, GO_THROUGH)
    went = {path.name: path.parent.name for path in papers.rglob("*") if path.is_file()} if papers.is_dir() else {}
    t.check(result_in(events, name) is not None and bool(went), "the first pass goes through the folder and says what it did")
    t.check(t.names(home.downloads) | set(went) == before and not (t.names(home.downloads) & set(went)),
            "every file is either where it was or in one of its folders: none is lost, none is doubled")
    right = [file for file, word in (("invoice_velo_parts_88120.pdf", "Suppliers"), ("kestrel_cycles_invoice_K5521.pdf", "Suppliers"),
                                     ("electricity_shop_october.pdf", "Bills"), ("water_bill_shop_q3.pdf", "Bills"))
             if went.get(file) == word]
    t.check(len(right) >= 3, f"the suppliers' invoices and the bills went where the rule says: {len(right)} of 4")
    stayed = [file for file in ("recipe_feijoada.txt", "dentist_reminder.pdf", "IMG_2207.jpg", "label_printer_setup.exe",
                                "staff_rota_november.docx") if file not in went]
    t.check(len(stayed) >= 4, f"what has nothing to do with suppliers or bills stayed: {len(stayed)} of 5")

    # A new file lands, and the thread that watches handles it.
    invoice = "invoice_velo_parts_88342.pdf"
    landed = t.lands(home.downloads, {invoice: SHOP_LATER[invoice]}, name)
    told = next((move for move in landed["moved"] if move["name"] == invoice), None)
    went_to = Path(told["to"]) if told else papers / "Suppliers"
    t.check(any(invoice in line for line in landed["lines"]), "while the new file is on its way and being read, the chores list says so")
    t.check(told is not None and (went_to / invoice).is_file() and went_to.parent == papers, "the new file is handled by itself: moved into one of its folders")
    t.check((papers / "Suppliers" / invoice).is_file(), "and an invoice from a supplier goes to Suppliers, as he wants")
    t.check(told is not None and bool(told.get("sort")) and len(told.get("steps", [])) >= 3
            and told.get("text", "").startswith(f"Put {invoice} in"),
            "the windows are told of the move, with its steps and what Undo needs")
    listing = t.chores()
    row = next((chore for chore in listing["chores"] if chore["name"] == name), {})
    t.check(str(row.get("last", "")).startswith(f"Put {invoice} in"), "its line in the chores list says what it just did")
    events = t.say("where did the velo invoice go?")
    t.check(invoice in words_in(events) and str(went_to) in words_in(events) and "kestrel" not in words_in(events).lower(),
            "asked where it went, it gives the whole path, of the files that were asked about")
    tickets = "concert_tickets_december.pdf"
    landed = t.lands(home.downloads, {tickets: SHOP_LATER[tickets]}, name)
    left = next((stay for stay in landed["stayed"] if stay["name"] == tickets), None)
    t.check(left is not None and (home.downloads / tickets).is_file(), "a file the rule leaves alone stays, and the windows are told why")
    events = t.say("why didnt you move the concert tickets?")
    t.check(f"{tickets} stayed in" in words_in(events), "asked why it stayed, it gives the reason it kept")
    events = t.say("paper sorter isnt working")
    t.check(question_in(events) is None and f"{name} is on" in words_in(events), "told it isn't working, it says it is on and what it did, from its record")

    # Undo, as the chores list's button does it.
    job = next((job for day in listing["days"] for job in day["jobs"] if job.get("undo") and invoice in job["text"]), None)
    back = t.engine.undo_move(job["sort"]) if job else 0
    print(f"\n  (Undo pressed in the chores list for: {job['text'] if job else 'nothing to undo'})")
    time.sleep(5)
    t.check(back == 1 and (home.downloads / invoice).is_file() and not (went_to / invoice).exists(),
            "Undo puts the file back, and it is not taken again")

    # Deleting it forgets everything kept about it.
    events = t.say("delete paper sorter")
    question = question_in(events)
    t.check(question is not None and question.id == DELETE_AGENT, "asked to delete it, it asks first")
    t.click(DELETE_AGENT, DELETE_IT)
    state = json.loads((noir.data_dir() / "folderwatch_state.json").read_text(encoding="utf-8"))
    kept = [key for key, value in state.items() if (name in value if isinstance(value, (list, dict)) else False)]
    t.check(not t.made() and not watch.is_on(name) and not kept, f"it is gone, switched off, and nothing is kept about it{': ' + str(kept) if kept else ''}")
    later = "invoice_kestrel_K5609.pdf"
    drop(home.downloads, {later: SHOP_LATER[later]})
    print(f"\n  (new in Downloads: {later})")
    time.sleep(8)
    t.check((home.downloads / later).is_file(), "a file that lands after that is left alone")
    t.check(any(job.get("agent") == name for job in t.engine.chore_done()), "what it did is still listed in the chores")


def called_off(t: Talk) -> None:
    """Called off in the middle, and called off at the card: nothing is made either time."""
    home = t.open(hobby_home)
    if home is None:
        return
    before = t.names(home.pictures)
    t.say("i have hundreds of photos of my hives in my pictures folder and i can never find the ones from one inspection")
    t.check(t.designing(), "the request opens the conversation")
    events = t.say("hm its not worth it. forget about it")
    t.check(not t.designing() and not t.made() and card_in(events) is None, "called off: the conversation is over and nothing is made")
    t.check(question_in(events) is None, "and it asks nothing more")
    events = t.work_out(t.say("can you make me something that explains a word i highlight in simple words"))
    t.check(t.card_up(), "another request is worked out to its card")
    events = t.click(CARD, "Cancel")
    t.check(not t.designing() and not t.made(), "Cancel on the card: nothing is made")
    t.check(t.names(home.pictures) == before, "no photo was touched")
    claims = [words for words in t.said if claims_done(words)]
    t.check(not claims, "it never says anything is on or made" + (f": {claims[0][:140]}" if claims else ""))


def aside(t: Talk) -> None:
    """Something else asked in the middle: answered, the helper kept aside, taken up again where it was."""
    home = t.open(house_home)
    if home is None:
        return
    before = t.names(home.downloads)
    designer_ = t.engine.designer
    events = t.say("can you help me keep my downloads folder tidy")
    t.check(t.designing() and question_in(events) is not None, "the request opens the conversation with a question")
    turns, slots = [dict(turn) for turn in t.sketch().turns], t.slots()
    events = t.say("is it going to rain in seattle tomorrow")
    t.check(designer_.aside is not None and not t.designing(), "a question about the world sets the helper aside; it is not thrown away")
    if designer_.aside is None:
        return
    asked = question_in(events)
    if asked is not None and asked.id == research.WEB:
        # The first question that would need the web asks whether it may look. Here it may
        # not, so nothing leaves this computer, and it answers from what it knows.
        events = t.click(research.WEB, research.NO_LOOK)
    asked = question_in(events)
    t.check(any(isinstance(event, NoirText) for event in events) and ends_asking(events, CARRY_ON),
            "the question is answered first, and under the answer it asks whether to carry on")
    events = t.say("whats 12 times 12")
    t.check("144" in words_in(events) and ends_asking(events, CARRY_ON),
            "a second question is answered too, and the same is asked again under it")
    t.check(designer_.aside is not None and designer_.aside.turns == turns and not t.made(),
            "the helper waits as it stood: its conversation has neither question in it")
    events = t.click(CARRY_ON, CARRY_ON_YES)
    back = question_in(events)
    t.check(t.designing() and t.slots() == slots and back is not None and back.text.startswith("Back to the helper we were working out."),
            "Carry on: it is back where it was, with the question that was open")
    t.check(t.design_tag not in " ".join(t._loaded()), "no model is asked for that: the design model is not in memory until they answer")
    events = t.say("mostly letters and things from the kids school, and bills. the rest is random stuff")
    events = t.work_out(events, ("things from the school go in a folder called School and bills in a folder called Bills. leave the rest where it is",))
    t.check(t.card_up(), "the conversation goes on to its card")
    if not t.card_up():
        return
    card_slots = t.slots()
    events = t.say("also leave the pictures alone")
    t.check(t.designing() and designer_.aside is None, "a message that is about the helper does not set it aside")
    events = t.work_out(events)
    card_slots = t.slots()
    events = t.say("how many legs does a spider have")
    if designer_.aside is None:
        print("        (the design model answered that itself, so the helper was never set aside here)")
        t.check(t.card_up(), "the card is still up")
    else:
        t.check("8" in words_in(events) or "eight" in words_in(events).lower(), "at the card too, the other question is answered")
        events = t.click(CARRY_ON, CARRY_ON_YES)
        again = result_in(events, TRY_OUT)
        t.check(t.designing() and t.slots() == card_slots and card_in(events) is not None and again is not None
                and again.text.startswith("The try-out from before"), "Carry on at the card: the same card comes back, with the try-out it had")
    t.before_the_button(home.downloads, before)
    t.create("yes")
    made = t.made()
    t.check(len(made) == 1 and made[0].slots.get("folder") == str(home.downloads), "the card that came back is live: a yes makes the helper")
    if made:
        t.click(FIRST_PASS, ONLY_NEW)

    # And dropped: another helper begun, set aside, and left.
    t.say("can you make me something that explains a word i highlight in simple words")
    events = t.say("whats the tallest mountain in africa")
    t.check(designer_.aside is not None and ends_asking(events, CARRY_ON), "a second helper is set aside the same way")
    events = t.click(CARRY_ON, DROP_IT)
    t.check(designer_.aside is None and not t.designing() and len(t.made()) == len(made), "Drop it: it is left, and nothing was made of it")
    events = t.say("thanks")
    t.check(question_in(events) is None, "and it is not asked about again")


def change(t: Talk) -> None:
    """A helper they already have, changed by talking: tried, renamed, saved."""
    rule = "Bills the shop has to pay go in Bills. Everything else stays where it is."
    home = t.home
    home = t.open(lambda home: (shop_home(home), aged(home.downloads, {"business_tax_notice_2026.pdf": SHOP_LATER["business_tax_notice_2026.pdf"]})),
                  seeds=(mover("Bills tidier", home, "Bills", rule),))
    if home is None:
        return
    before = t.names(home.downloads)
    events = t.work_out(t.say("change bills tidier so that anything from the tax office goes into a folder called Tax"))
    slots = t.slots()
    t.check(t.designing() and t.sketch().editing and t.card_up() and card_in(events) is not None
            and card_in(events).actions[0] == SAVE_CHANGES, "the change is talked through and ends in a card that saves changes")
    t.check(sorted(name.casefold() for name in parts.choices_of(slots)) == ["bills", "tax"], f"its folders are Bills and Tax now: {parts.choices_of(slots)}")
    rows = {row.get("name"): str(row.get("choice") or "") for row in (t.sketch().tried or [])} if t.designing() else {}
    t.check(rows.get("business_tax_notice_2026.pdf", "").casefold() == "tax", "in the try-out the tax notice goes to Tax")
    t.check(store.find_agent("Bills tidier").slots.get("instruction") == rule and t.names(home.downloads) == before,
            "the helper they have is as it was, and nothing has moved")
    claims = [words for words in t.said if re.search(r"\b(i have|i've) (updated|changed)\b", words, re.IGNORECASE)]
    t.check(not claims, "it never says the helper has been changed before they save" + (f": {claims[0][:140]}" if claims else ""))
    if not t.card_up():
        return
    events = t.say("call it Paperwork tidier")
    t.check(t.slots().get("name") == "Paperwork tidier" and result_in(events, TRY_OUT) is None, "a new name is taken without trying it again")
    events = t.create("save it")
    saved = [agent.name for agent in store.list_agents()]
    t.check(saved == ["Paperwork tidier"] and "tax" in str(store.find_agent("Paperwork tidier").slots.get("instruction")).lower(),
            f"saved: the one helper has the new name and the new rule: {saved}")
    question = question_in(events)
    t.check(question is not None and question.id == FIX_AGENT, "it was off, so it asks whether to switch it on")
    if question is not None and question.id == FIX_AGENT:
        t.click(FIX_AGENT, SWITCH_IT_ON)
        t.check(t.engine.folderwatch.is_on("Paperwork tidier"), "and a click switches it on")


def by_hand(t: Talk) -> None:
    """A file put somewhere by hand, which becomes the rule; and one that is only that file."""
    rule = ("Invoices and delivery notes from my suppliers go in Suppliers. Bills the shop has to pay go in Bills. "
            "Everything else stays where it is.")
    home = t.home
    home = t.open(shop_home, seeds=(mover("Shop papers", home, "Suppliers, Bills", rule),))
    if home is None:
        return
    name, watch = "Shop papers", t.engine.folderwatch
    t._step(t.engine.set_agent(name, True), f"[switches {name} on in the helpers list]")
    first = "warranty_registration_truing_stand.pdf"
    landed = t.lands(home.downloads, {first: SHOP_LATER[first]}, name)
    t.check((home.downloads / first).is_file() and any(stay["name"] == first for stay in landed["stayed"]),
            "a paper the rule says nothing about stays where it landed")
    events = t.say("put the truing stand warranty in Warranties")
    saved = store.find_agent(name)
    t.check((home.downloads / "Warranties" / first).is_file() and {"name": first, "choice": "Warranties"} in (saved.slots.get("examples") or []),
            "told to, it moves the file there and keeps that as an example")
    t.check(ends_asking(events, RULE_FROM_MOVE), "and asks whether files like it should always go there")
    events = t.work_out(t.click(RULE_FROM_MOVE, CHANGE_THE_RULE))
    t.check(t.designing() and t.sketch().editing and t.card_up() and card_in(events) is not None
            and card_in(events).actions[0] == SAVE_CHANGES, "a yes opens the change, which ends in a card that saves changes")
    t.check(store.find_agent(name).slots.get("instruction") == rule, "the rule they have is as it was until they save")
    if not t.card_up():
        return
    events = t.click(CARD, SAVE_CHANGES)
    saved = store.find_agent(name)
    t.check(saved is not None and saved.slots.get("instruction") != rule and "warrant" in saved.slots.get("instruction", "").lower(),
            "saved: the rule now speaks of such papers")
    t.check(watch.is_on(name) and question_in(events) is None, "it was on and stays on, with nothing more asked")
    second = "warranty_registration_compressor.pdf"
    landed = t.lands(home.downloads, {second: SHOP_LATER[second]}, name)
    t.check((home.downloads / "Warranties" / second).is_file(), "the next paper like it goes there by the rule, with nobody saying so")

    # And a no: that one file, and nothing more is asked for this helper.
    rota = "staff_rota_december.docx"
    t.lands(home.downloads, {rota: SHOP_LATER[rota]}, name)
    events = t.say("put the staff rota in Staff")
    asked = ends_asking(events, RULE_FROM_MOVE)
    t.check((home.downloads / "Staff" / rota).is_file() and asked, "another file put somewhere by hand is asked about too")
    if asked:
        events = t.click(RULE_FROM_MOVE, JUST_THIS_ONE)
        t.check(not t.designing() and "just this one" in words_in(events).lower(), "No: only that file, and no conversation opens")
    prices = "price_list_summer.xlsx"
    t.lands(home.downloads, {prices: SHOP_LATER[prices]}, name)
    events = t.say("put the summer price list in Staff")
    t.check((home.downloads / "Staff" / prices).is_file() and question_in(events) is None,
            "after a no, the next file put there by hand is moved and nothing is asked")


def trouble(t: Talk) -> None:
    """Told a helper isn't working: the mechanics are checked first, and what is left is put right by talking."""
    rule = "Say what the Japanese text means, in English."
    seed = store.Agent(name="Japanese meaning", blueprint=parts.CUSTOM, slots={
        "when": parts.WHILE_ON, "then": parts.SHOW, "skip_language": "English", "show": BUBBLE, "keep": UNTIL_UNHIGHLIGHT,
        "instruction": rule, "name": "Japanese meaning"})
    home = t.open(hobby_home, seeds=(seed,))
    if home is None or t.engine.quick is None:
        return
    name = seed.name
    events = t.say("japanese meaning isnt showing anything")
    question = question_in(events)
    t.check(question is not None and question.id == FIX_AGENT and not t.designing(), "switched off: it says so, and offers to switch it on")
    events = t.click(FIX_AGENT, SWITCH_IT_ON)
    t.check(t.engine.quick.is_on(name), "a click switches it on")
    events = t.say("japanese meaning still isnt showing anything")
    t.check("no highlighted text has reached it" in words_in(events) and not t.designing(),
            "on, and nothing highlighted yet: it says that, and changes nothing")
    t.highlight("The weather is nice today.")
    events = t.say("japanese meaning is not showing anything")
    t.check("leaves out" in words_in(events) and "English" in words_in(events) and not t.designing(),
            "the last highlight was one it leaves out: it says which, and changes nothing")
    shown = t.highlight("今日は天気がいいですね。散歩に行きませんか。")
    t.check(bool(shown), "a Japanese sentence gets its bubble")
    events = t.say("japanese meaning doesnt work right, it gives me a whole paragraph when i just want a few words")
    t.check(t.designing() and t.sketch().editing and t.sketch().replaces == name,
            "nothing mechanical is wrong, so the report opens a conversation about changing it")
    t.check(any(isinstance(event, Thinking) and "Checked" in event.text for event in events), "and it says first what it checked")
    events = t.work_out(events)
    t.check(t.card_up() and t.slots().get("instruction") != rule, "the conversation ends in a card with another rule")
    t.check(store.find_agent(name).slots.get("instruction") == rule, "the helper is as it was until they save")
    if not t.card_up():
        return
    t.create()
    saved = store.find_agent(name)
    t.check(saved is not None and saved.slots.get("instruction") != rule and t.engine.quick.is_on(name), "saved, and still switched on")
    after = t.highlight("今日は天気がいいですね。散歩に行きませんか。")
    t.check(bool(after) and bool(shown) and len(after[-1][1]) <= len(shown[-1][1]), "and the next bubble is no longer than the one they complained of")


CONVERSATIONS = (thin, notes, highlight, chat, documents, cannot, korean, at_once, called_off, aside, change, by_hand, trouble)


# ---------------------------------------------------------------- the whole play


class Plan:
    """The user's own ChatGPT plan as the model that designs, through Codex, for one
    conversation: to see the plan's path work for real. Codex is run with the home folder
    the user really has (its sign-in is there); what it is sent is the designer's note, a
    made-up person's words and the made-up home's folder names and counts, and it is
    checked for the user's own name before it goes."""

    def __init__(self, real_env: dict, real_home: Path):
        self.shim = RealHome(real_env)
        self.accounts = accounts_mod.Accounts(run=self.shim.run, popen=self.shim.Popen, home=real_home)
        self.own = [word for word in {real_home.name, str(real_home)} if word]
        self.status = self.accounts.status(accounts_mod.CODEX, fresh=True)
        self.model_id = self.model_name = ""
        self.calls: list[dict] | None = None  # the conversation's own list of what each call took

    def ready(self) -> bool:
        models = self.status.get("models") or []
        if not (self.status.get("installed") and self.status.get("signed_in") and models):
            return False
        self.model_id, self.model_name = models[0]["id"], models[0]["name"]
        return True

    def model(self) -> DesignModel:
        # No persona goes along (the app sends Noir's, which says what this computer is):
        # nothing of the user's own is to be in what this play sends.
        talker = accounts_mod.AppModel(self.accounts, accounts_mod.CODEX, self.model_id, "")
        fill = talker_form(talker, self.model_id)

        def form(note: str, turns: list[dict], schema: dict) -> dict:
            sent = note + " ".join(turn["content"] for turn in turns)
            if any(word.casefold() in sent.casefold() for word in self.own):
                raise designer.DesignerError("the eval would have sent something of the user's own, so it sent nothing")
            before, started = usage.summary().get(accounts_mod.CODEX, {}).get("last"), time.monotonic()
            was, accounts_mod.subprocess = accounts_mod.subprocess, self.shim
            try:
                filled = fill(note, turns, schema)
            finally:
                accounts_mod.subprocess = was
            last = usage.summary().get(accounts_mod.CODEX, {}).get("last") or {}
            read, wrote = (int(last.get("read", 0)), int(last.get("wrote", 0))) if last != before else (0, 0)
            if self.calls is not None:
                self.calls.append({"model": "plan", "seconds": time.monotonic() - started, "read": read, "wrote": wrote,
                                   "loaded": [], "form": filled, "note": note})
            return filled

        return DesignModel(form, self.model_name, here=False)


class Play:
    """One whole play: every conversation, then the checks, the times and the graphics card."""

    def __init__(self, root: Path, tag: str = "", only: tuple = (), forms: bool = False, plan: Plan | None = None):
        self.root, self.tag, self.only, self.forms, self.plan = root, tag, only, forms, plan
        self.designer_name = ""
        self.talks: list[Talk] = []
        self.card_at_start = card_memory()
        self.checks: list[bool] = []  # about the whole play, not one conversation
        self.failed: list[str] = []

    def check(self, condition: bool, what: str) -> None:
        print(("  OK    " if condition else "  FAIL  ") + what)
        self.checks.append(bool(condition))
        if not condition:
            self.failed.append(what)

    def go(self) -> bool:
        for script in CONVERSATIONS:
            if self.only and script.__name__ not in self.only:
                continue
            talk = Talk(self, script.__name__, (script.__doc__ or "").strip())
            self.talks.append(talk)
            print(f"\n{'-' * 100}\n{talk.name}: {talk.title}\n{'-' * 100}")
            try:
                script(talk)
            except Exception as problem:  # noqa: BLE001 - one conversation that breaks must not end the play
                traceback.print_exc(file=sys.stdout)
                talk.check(False, f"the conversation ran to its end (it broke: {type(problem).__name__}: {problem})")
            finally:
                talk.close()
        self.sum_up()
        return bool(self.talks) and all(all(talk.checks) for talk in self.talks) and all(self.checks)

    def check_whole(self) -> None:
        """What holds for the play as a whole, from what every conversation took: the room a
        design model on this computer is given, and the graphics memory."""
        forms = [form for talk in self.talks for turn in talk.turns for form in turn["forms"]]
        here = any(talk.design_tag for talk in self.talks)  # a design model on this computer, not a plan's
        if not forms and not here:
            return
        print(f"\n{'=' * 100}\nTHE PLAY AS A WHOLE\n{'=' * 100}")
        if forms and self.plan is None:
            # Past its room Ollama drops the earliest turns of the conversation, or the reply
            # runs out of room, and nothing says so: a note or a conversation that grows has
            # to fail the play well before that. The eval of the setups that came before
            # held its longest turn to the same share of its room, and lost that check when
            # it was replaced; the whole plays of 22 Nov 2026 filled 71% at most.
            most = max(form["read"] + form["wrote"] for form in forms)
            self.check(most < DESIGN_CONTEXT * ROOM_SHARE,
                       f"the fullest form held {most:,} tokens, well inside the {DESIGN_CONTEXT:,} a design model "
                       "on this computer is given")
        if here:
            both = [call for talk in self.talks for call in (talk.ollama.calls if talk.ollama is not None else [])
                    if talk.design_tag and any(talk.design_tag in name for name in call["loaded"])
                    and any(name.split(":")[0] == noir.NOIR_MODEL for name in call["loaded"])]
            self.check(not both, "the design model and the built-in model were never in memory together")

    def sum_up(self) -> None:
        self.check_whole()
        print(f"\n{'=' * 100}\nTHE CHECKS\n{'=' * 100}")
        for talk in self.talks:
            print(f"  {talk.name:<11} {sum(talk.checks):>3} of {len(talk.checks):<3} {'' if all(talk.checks) else 'FAILED:'}")
            for what in talk.failed:
                print(f"      - {what}")
        if self.checks:
            print(f"  {'the play':<11} {sum(self.checks):>3} of {len(self.checks):<3} {'' if all(self.checks) else 'FAILED:'}")
            for what in self.failed:
                print(f"      - {what}")
        passed = sum(sum(talk.checks) for talk in self.talks) + sum(self.checks)
        total = sum(len(talk.checks) for talk in self.talks) + len(self.checks)
        print(f"  {passed} of {total} checks passed.")

        print(f"\n{'=' * 100}\nSECONDS AND TOKENS A TURN ({self.designer_name or 'no design model'})\n{'=' * 100}")
        every = []
        for talk in self.talks:
            turns = [turn for turn in talk.turns if turn["forms"]]
            every += turns
            if not turns:
                print(f"  {talk.name:<11} no turn of the design model")
                continue
            forms = [form for turn in turns for form in turn["forms"]]
            print(f"  {talk.name:<11} {len(turns):>2} turns of the design model, {sum(t['seconds'] for t in turns) / len(turns):5.1f} s a turn "
                  f"(longest {max(t['seconds'] for t in turns):.1f} s); {len(forms)} forms, read {sum(f['read'] for f in forms) // len(forms):,} "
                  f"and wrote {sum(f['wrote'] for f in forms) // len(forms):,} tokens a form on average")
        forms = [form for turn in every for form in turn["forms"]]
        if every and forms:
            most = max(form["read"] + form["wrote"] for form in forms)
            print(f"  all: {len(every)} turns, {sum(t['seconds'] for t in every) / len(every):.1f} s a turn on average, longest "
                  f"{max(t['seconds'] for t in every):.1f} s; {len(forms)} forms; the fullest form held {most:,} tokens"
                  + (f" of the {DESIGN_CONTEXT:,} a design model on this computer is given" if self.plan is None else ""))
        seconds = sum(turn["seconds"] for talk in self.talks for turn in talk.turns)
        print(f"  the whole play: {seconds:.0f} s in {sum(len(talk.turns) for talk in self.talks)} things typed or clicked")
        if self.plan is not None:
            # Added up from each answer's own count: the usage file of a conversation is in its
            # made-up data folder, left by now, so reading the day's total here said 0.
            charged = [form for form in forms if form["model"] == "plan"]
            print(f"  the plan was charged, by its own count: {sum(f['read'] for f in charged):,} tokens read and "
                  f"{sum(f['wrote'] for f in charged):,} written in {len(charged)} answers")

        print(f"\n{'=' * 100}\nTHE GRAPHICS CARD (nvidia-smi, MiB)\n{'=' * 100}")
        both = []
        with_design, with_own = [], []
        for talk in self.talks:
            calls = talk.ollama.calls if talk.ollama is not None else []
            both += [call for call in calls if talk.design_tag and any(talk.design_tag in name for name in call["loaded"])
                     and any(name.split(":")[0] == noir.NOIR_MODEL for name in call["loaded"])]
            for turn in talk.turns:
                if turn["card"] is None:
                    continue
                if talk.design_tag and any(talk.design_tag in name for name in turn["loaded"]):
                    with_design.append(turn["card"])
                elif any(name.split(":")[0] == noir.NOIR_MODEL for name in turn["loaded"]):
                    with_own.append(turn["card"])
        print(f"  before the play: {self.card_at_start}")
        if with_design:
            print(f"  with the design model in memory, after a turn: {min(with_design):,} to {max(with_design):,}")
        if with_own:
            print(f"  with the built-in model in memory, after a turn: {min(with_own):,} to {max(with_own):,}")
        print(f"  the two in memory together, seen right after something was asked of a model: {len(both)} time{'' if len(both) == 1 else 's'}")
        try:
            left = sorted(one["name"] for one in Counted().loaded())
        except Exception:  # noqa: BLE001
            left = ["(Ollama did not answer)"]
        print(f"  after the play: {card_memory()}; in memory: {', '.join(left) or 'nothing'}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # A model's words, or a folder's name, may hold a letter this console can't show. It is
    # printed as "?": it must not end the run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    names = [script.__name__ for script in CONVERSATIONS]
    if "--list" in argv:
        for script in CONVERSATIONS:
            print(f"{script.__name__:<11} {(script.__doc__ or '').strip()}")
        return 0
    only, tag, plan_app, rest = [], "", "", list(argv)
    while rest:
        word = rest.pop(0)
        if word == "--only":
            while rest and not rest[0].startswith("--"):
                only.append(rest.pop(0))
        elif word == "--plan":
            plan_app = rest.pop(0) if rest and not rest[0].startswith("--") else accounts_mod.CODEX
        elif not word.startswith("--"):
            tag = word
    unknown = [name for name in only if name not in names]
    if unknown:
        print(f"No conversation is called {', '.join(unknown)}. There are: {', '.join(names)}.")
        return 2
    plan = None
    if plan_app:
        if plan_app != accounts_mod.CODEX:
            print("Only the ChatGPT plan can be played with (--plan codex): through Claude Code every turn costs "
                  "about 29k tokens of the plan.")
            return 2
        if len(only) != 1:
            print("A plan is played with one conversation at a time: name it with --only.")
            return 2
        plan = Plan(dict(os.environ), Path.home())
        if not plan.ready():
            print(f"The ChatGPT plan can't be used here: Codex is {'installed' if plan.status.get('installed') else 'not installed'}"
                  f"{'' if plan.status.get('signed_in') else ', not signed in'}"
                  f"{'' if plan.status.get('models') or not plan.status.get('signed_in') else ', and listed no models'}.")
            return 2
    # Ollama's program is looked for under the user's own LOCALAPPDATA, which a made-up home
    # points somewhere else, so the engine of a conversation can't start it: it is started
    # here, before that. (A play once failed at its first line with Ollama simply stopped.)
    try:
        Counted().ensure_running()
    except Exception:  # noqa: BLE001 - each conversation then says so and fails on its own
        pass
    root = Path(tempfile.mkdtemp(prefix="noir-designer-eval-"))
    # Between two conversations the app's folders point at nothing of the user's either: a
    # thread of a conversation that is over, still finishing, writes into this folder.
    nowhere = Home(root / "between")
    nowhere.move_in()
    started = time.time()
    play = Play(root, tag, tuple(only), "--forms" in argv, plan)
    print(f"{'=' * 100}\n{plan.model_name + ' through the ChatGPT plan' if plan else tag or 'the design model this computer would use'}"
          f", built-in model {noir.NOIR_MODEL}; made-up homes in {root}\n{'=' * 100}")
    try:
        passed = play.go()
    finally:
        nowhere.leave()
        if "--keep" in argv:
            print(f"\nkept: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    checks = [check for talk in play.talks for check in talk.checks] + play.checks
    print(f"\n{play.designer_name or tag or 'nobody'}: {sum(checks)} of {len(checks)} checks passed in {time.time() - started:.0f}s")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
