# FSAE Telemetry System Design — Conversation Log

---

## Antenna Placement

**Q:** What would the best spot for the antenna be considering the antenna is for 2.5 to 5GHz and by rules cannot be above the main roll hoop?

**A:**

The short answer is: **as high on the main hoop as the rules will let you, on the rear face, standing off the tube on an insulating bracket, with the tip of the antenna a few millimetres below the hoop plane.**

### Why the top of the hoop wins

At 2.4 GHz λ is about 125 mm; at 5.8 GHz it's around 52 mm. Nothing at these frequencies diffracts usefully around obstacles — it's essentially line-of-sight. The two biggest blockers on a formula car are the driver and the carbon bodywork, and the hoop top is the only legal point that clears both. The driver's head is mostly water and eats several dB at 2.4 GHz, so if the antenna sits at helmet height on the centreline you lose the forward direction — exactly when the car is coming down the straight at the pit antenna. Most rulesets already require the hoop to clear the helmet by 50 mm or so, which conveniently puts the antenna above the driver.

### Standoff is not optional

The hoop is a steel tube roughly a wavelength long at 2.4 GHz and it will detune and reshape the pattern if the radiator is close to it. Get at least λ/4 (~31 mm at 2.4 GHz) between the element and the tube; 50–60 mm is better if packaging allows. Use Delrin, PEEK, G10, or a printed bracket — not an aluminium tab.

### Element type

Pick a dual-band vertical dipole rather than a monopole/whip. Up there you have no meaningful ground plane, and a monopole without one will radiate off the coax shield, which turns the cable into part of the antenna and gives you an unpredictable pattern that changes with routing. A dipole is self-contained. Vertical polarisation to match the base station.

### Mind the pattern notch

Whichever side of the hoop you mount on, the tube shadows the opposite direction — you'll typically see a 5–10 dB notch over a fairly narrow azimuth sector. Since the car sweeps all 360° relative to the pit over a lap, that notch will show up as a periodic dropout at one point on track. Two options: mount on the centreline directly behind the hoop with a generous standoff so the notch is narrow and points forward-ish, or run two antennas on either side into a diversity-capable receiver. If your telemetry radio has two connectors, use them.

### Practical points

- Measure the exclusion plane against the *tip* of the antenna, not the base. Radome plus connector plus bracket adds up fast, and scrutineering will measure the highest point. Leave 10 mm of margin.
- Keep the coax short. RG-316 runs roughly 1.2 dB/m at 2.4 GHz and closer to 2 dB/m at 5.8 GHz, so a 1.5 m run to a floor-mounted radio can cost you a third of your link budget in the cable alone. Use LMR-195 or LMR-240 if the run has to be long, or move the radio up toward the antenna.
- Strain-relieve the connector. Hoop-top vibration on a stiff car will work an SMA loose or fatigue the centre pin within a season.
- Keep it away from the inverter, HV cabling, and ignition system — those are broadband noise sources.
- If you also run GPS, keep the two antennas at least 150 mm apart.

---

## Base Station and Diversity Setup

**Q:** The base station should be fixed — it will be my laptop. Do I need a receiver antenna as well? I think the best solution is one that has the 2 antennas on either side of the main roll hoop to prevent signal loss around part of the track. Can you explain more of the setup for this and potentially source some parts that would work?

**A:**

Yes — you definitely need an antenna at both ends.

### Put the gain at the base station, not on the car

Antenna gain is reciprocal — it helps transmit and receive equally. The car has to be omnidirectional because it rotates through 360° relative to you every lap, so you're stuck with roughly 2–3 dBi there. But the base station is fixed, so you can use an 8 dBi collinear omni and get +6 dB on *both* directions of the link. Six dB is a doubling of range in free space.

**Height at the base station matters as much as gain.** At 2.4 GHz over a 200 m path, the first Fresnel zone is about 2.5 m in radius at the midpoint. Get the base antenna up on a 2–3 m stand. A laptop sitting on a table with a dongle radiates into the ground plane.

### Band choice — pick 2.4 GHz as primary

Free-space path loss at 200 m is about 86 dB at 2.4 GHz and 94 dB at 5.8 GHz — an ~8 dB penalty for 5 GHz before accounting for its worse diffraction. The counterargument is congestion: 2.4 GHz at a competition event can be very busy. The practical answer is to run dual-band hardware at both ends and switch as needed.

### What diversity actually gets you

Your instinct is right, but the prerequisite is: **your car-side radio needs two antenna chains.** A 2×2 chipset gives you true receive-side maximal-ratio combining — up to 3 dB of gain in normal conditions, and more importantly, a deep fade on one antenna doesn't kill the packet. The hoop tube shadows one antenna over a sector of azimuth — exactly the sector the *other* antenna sees clearly. The two nulls are complementary.

Separation needs to be at least λ/2 (62 mm at 2.4 GHz). Across a hoop you'll get 300–400 mm — comfortably enough.

### Parts

**Car side (×2):**
- Taoglas GW.48.A151 — dual-band 2.4/5.8 GHz dipole, IP67, IK05 impact-rated, 89.5 mm tall, 1.82 dBi at 2.4 GHz, 3 dBi at 5.8 GHz
- Short RG-316 or LMR-100 pigtails, keep each under ~700 mm
- Delrin/PEEK/G10 brackets, ≥30 mm standoff from the tube

**Base station:**
- Alfa AWUS036ACM — dual-band USB adapter, 2×2 MT7612U chipset, two RP-SMA connectors, good Linux driver support
- Mikrotik MKT-AOA-24-5-8dBi — outdoor dual-band omni, 6 dBi at 2.4 GHz, 8 dBi at 5 GHz, N-female
- Photo/speaker stand as mast (2–3 m), plus mast clamp

**Important:** mount the USB adapter at the antenna with a short 300 mm pigtail and run an active USB extension down to the laptop. A 5 m run of RG-58 at 2.4 GHz eats 4–5 dB.

**Regulatory note (ISED RSS-247):** cap is 36 dBm EIRP in the 2.4 GHz band. A 20 dBm radio into an 8 dBi antenna is 28 dBm — fine.

---

## neoVI PI Hardware Audit

**Q:** I am using an Intrepid Control Systems neoVI PI which is based on a Raspberry Pi 4. Can you look up the documentation to see the specs and see what's available to us?

**A:**

### What you've got

The neoVI PI is built around a Raspberry Pi 4 Compute Module with quad 64-bit cores and gigabit Ethernet, paired with Intrepid's CAN FD technology. Specs include: 1× gigabit Ethernet, 4× high-speed USB host ports with high current sourcing, M.2 NVMe SSD, 5–60 V supply, −20 °C to +80 °C temperature range.

### The bad news for diversity

The CM4's wireless is a Cypress CYW43455 supporting 2.4 and 5 GHz 802.11ac plus Bluetooth 5.0. It has an on-board antenna plus a U.FL connector, selected via `dtparam=ant1` or `dtparam=ant2` in config.txt. Those two antenna paths are **an RF switch, not two chains**. The chip is 2×2-capable, but only a single antenna is ever used. The onboard radio is effectively 1×1. No diversity, no MRC, no STBC.

Using a different antenna from the official Raspberry Pi kit (SC0480, 2 dBi, 108 mm, SMA female) also requires separate certification.

### The solution: use the USB ports

Put an Alfa AWUS036ACM on the *car* as well as the base station. That gives a genuine 2×2 radio with two RP-SMA connectors on each end, and the diversity plan works. The MT7612U is handled by the in-kernel `mt76x2u` driver — plug-and-play on current Raspberry Pi OS, no out-of-tree modules.

**Architecture:** mount the dongle *up by the hoop* and run USB down to the neoVI. USB loses nothing over a couple of metres; coax at 5.8 GHz loses ~2 dB/m.

**Key gotcha — disable scatter-gather:** there is a known failure where the MT7612U crashes on Pi 4 USB 3.0. Fix: add `mt76-usb disable_usb_sg=1` as a module parameter.

**Don't run both radios on 2.4 GHz.** Disable the onboard radio (`dtoverlay=disable-wifi`) or split bands — e.g. onboard as a 2.4 GHz pit-lane AP, Alfa on 5 GHz UNII-3 for the telemetry link.

**Power:** the RFD900x can draw ~800 mA–1 A at full transmit. Either power the modem from a vehicle 5 V rail and use USB/UART for data only, or dial transmit power down to 20 dBm.

---

## 900 MHz Option — RFD900x

**Q:** I was curious about the lower frequency radio solution that Carnegie Mellon used and if that was an option with our setup. There was also the issue with using the Alfa AWUS036ACM — I am worried it will break on the car.

**A:**

Both good instincts. The RFD900x resolves the Alfa problem as a side effect.

### The RFD900x

- 902–928 MHz band, license-free in Canada (ISED)
- Diversity antenna support built into firmware — first-class, not coaxed
- 1 W (+30 dBm) transmit power, adjustable in 1 dB steps
- Air data rates: up to 500 kbit/s
- Sensitivity: −111 dBm at 12 kbps, −105 dBm at 64 kbps, −98 dBm at 200 kbps
- Temperature range: −40 °C to +85 °C
- Weight: 14 g, 30 × 57.7 × 12.8 mm
- ESD-protected and filtered I/O, transmit low-pass filter, >20 dB LNA, RX SAW filter

### The numbers are not close (vs Wi-Fi)

| Factor | Advantage |
|---|---|
| Transmit power: +30 dBm vs +20 dBm | +10 dB |
| Path loss at 915 MHz vs 2450 MHz | +8.6 dB |
| Receiver sensitivity vs Wi-Fi floor | ~+15 dB |
| **Total** | **~34 dB** |

At 300 m: ~−45 dBm received vs −105 dBm floor = **60 dB of margin**. You'd dial power *down* to 20 dBm and still never notice a dropout. 900 MHz also diffracts far better around tyre walls and other cars.

### What it costs

- **Bandwidth:** 64–224 kbps usable. You cannot stream a full CAN FD bus. Log everything locally, stream a selected subset live.
- **Serial pipe, not a network:** SiK firmware gives transparent bytes in, bytes out with FHSS and ECC. You write the framing — a Pi script selecting and downsampling CAN frames, pushing them to `/dev/ttyUSB0`.
- **Bigger antennas:** at 915 MHz a half-wave dipole is ~165 mm. Take the dipoles over the quarter-wave monopoles (monopoles need a ground plane).

### Recommended architecture

- **900 MHz RFD900x:** live telemetry, critical channels, all lap
- **Wi-Fi/Ethernet:** pit only, bulk log transfer from NVMe
- **Video:** recorded locally, synced by timestamp post-session

### Power note

ArduPilot's docs flag this: many autopilots can't power RFD900 at full transmit power. Power the modem from the vehicle 5 V rail and use the USB/UART for data only, or dial to 20 dBm. 20 dBm still leaves ~50 dB of margin at 300 m.

### Buy the two-modem bundle

You need one on the car and one on the laptop. Bundles include the dipoles and an FTDI USB cable for the ground-station end.

---

## F1 Comparison — 1.5 GHz and Full Bus Streaming

**Q:** I was curious about this article on F1 telemetry (las-motorsport.com). It seems F1 uses a 1.5 GHz radio and sends a huge amount of channels. Would it be possible to do something similar?

**A:**

### Why 1.5 GHz isn't the point

1.5 GHz is not an ISM band — it's licensed spectrum, coordinated event by event with the national regulator. In Canada that region is largely allocated to aeronautical and mobile-satellite services. ISED is not going to issue a student team a licence to transmit in it. F1 uses it because they get exclusive, interference-free spectrum with generous power limits. You're confined to ISM.

### The two things you *can* steal from F1

1. **Onboard buffering with retransmit.** When coverage drops, the car buffers data onboard and sends it once signal returns. This is free — you already have an NVMe SSD. Log everything at full rate locally, stream what fits live, backfill the gaps opportunistically. Dropouts become latency rather than data loss.

2. **Multiple receive sites.** F1 compares its trackside antenna handoff to a mobile network. Two or three receivers around your test site, Ethernet-backhauled to a switch at your laptop, is entirely affordable at student scale and does more for coverage than any antenna choice.

### Bandwidth reality

| Stream | Required bandwidth |
|---|---|
| Full CAN traffic (naive) | 1–2 Mbit/s |
| Video at 480p compressed | 0.5–1 Mbit/s |
| Video at 720p usable | 2–4 Mbit/s |
| **Total** | **2–6 Mbit/s** |

RFD900x practical throughput: ~200–250 kbit/s. You're short by a factor of 10–25. This is an order-of-magnitude problem, not a tuning problem.

### Recommended approach

- **Take video off the radio entirely.** Record onboard. Sync by timestamp post-session. Live video is almost never actionable in the moment.
- **900 MHz, always on.** 30–50 critical channels at 10–20 Hz. Tens of kbps. Works everywhere.
- **Wi-Fi, opportunistic.** When the car is in range of a receive site, drain the buffered full-rate bus log at multi-Mbit/s. Full data on your laptop within a lap or two of it being recorded.

---

## CAN Bus Load Analysis — Full Bus Over 900 MHz

**Q:** We run the bus at 500 kbps with around 70% load maximum. We have 2 CAN buses, the other at around 20% load but the same speed. We are on classic CAN.

**A:**

### Frame rate calculation

A standard 11-bit CAN frame with 8 data bytes runs ~125–130 bits on the wire including stuffing and interframe space. Using ~120 bits per frame as a working figure:

| Bus | Load | Bit rate | Frame rate |
|---|---|---|---|
| Bus 1 | 70% | 350 kbit/s | ~2,900 frames/s |
| Bus 2 | 20% | 100 kbit/s | ~830 frames/s |
| **Combined** | | | **~3,700–4,000 frames/s** |

### Uncompressed transport

A sane wire record: 8-byte timestamp + 4-byte arbitration ID + 1-byte channel + 1-byte DLC/flags + 8-byte payload = 22 bytes. Add framing: ~24 bytes.

**4,000 frames/s × 24 bytes = ~780 kbit/s peak**

### Compressed transport

CAN traffic is extraordinarily compressible:

- **Delta timestamps:** frames arrive a few hundred microseconds apart. Encode the delta: 8 bytes → 1–2 bytes
- **ID dictionary:** index arbitration IDs (fewer than 256 unique): 4 bytes → 1 byte
- **Payload deltas:** XOR against last payload for same ID — most bytes go to zero and compress to almost nothing

Result: ~5–8 bytes per frame → **4,000 × 7 bytes ≈ 220 kbit/s peak**, ~130–160 kbit/s average.

Piping naive 24-byte records through LZ4 or zstd typically gives 4:1 to 8:1 on CAN data with the same result.

### Verdict: the full bus fits over 900 MHz

- RFD900x at 500 kbit/s air rate → ~200–250 kbit/s usable payload
- Compressed stream: 130–160 kbit/s average, peaks to ~220 kbit/s
- **Headroom: roughly 40%**

Sensitivity at 500 kbit/s degrades to ~−93 dBm. You were receiving ~−45 dBm at 300 m. Still **48 dB of margin** — nowhere near the range limit.

### Architecture update

The 900 MHz link becomes the **primary full-bus link**, not a "critical channels only" fallback. Wi-Fi drops to a pit convenience for pulling the uncompressed archive and video. No dongle on the car, no second pair of hoop antennas, no sealed consumer hardware enclosure.

**Buffering:** a 10-second dropout backs up ~200 kB. A 2-minute blackout is ~2.4 MB. With 40% headroom, a 10-second gap drains in ~15 seconds of good signal.

### Two things to check before committing

1. **Measure your actual compression ratio.** Run zstd at high level against an existing log file. If you have a lot of noisy analog channels where the low bits dither, compression will be worse than the assumed 4:1.

2. **70% load is near the practical ceiling for classical CAN.** Low-priority frames may see unpredictable arbitration delay. Consider whether traffic can be moved to Bus 2 (sitting at 20%). Rebalancing would also reduce peak transport rate.

---

*Conversation exported — July 30, 2026*
