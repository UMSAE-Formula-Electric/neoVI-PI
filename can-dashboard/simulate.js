/**
 * CAN Data Simulator — pipe this into server.js for testing
 * Usage: node simulate.js | node server.js
 */

const SIGNALS = [
  { channel: "CAN0", id: "0x100", name: "EngineControl", signal: "RPM",         unit: "rpm",  min: 700,   max: 7000, freq: 50  },
  { channel: "CAN0", id: "0x100", name: "EngineControl", signal: "Throttle",     unit: "%",    min: 0,     max: 100,  freq: 50  },
  { channel: "CAN0", id: "0x100", name: "EngineControl", signal: "CoolantTemp",  unit: "°C",   min: 70,    max: 110,  freq: 100 },
  { channel: "CAN0", id: "0x101", name: "TransmissionControl", signal: "Gear",   unit: "",     min: 1,     max: 6,    freq: 200 },
  { channel: "CAN0", id: "0x101", name: "TransmissionControl", signal: "OilTemp",unit: "°C",   min: 60,    max: 130,  freq: 500 },
  { channel: "CAN0", id: "0x200", name: "ABS",            signal: "WheelFL",     unit: "km/h", min: 0,     max: 200,  freq: 10  },
  { channel: "CAN0", id: "0x200", name: "ABS",            signal: "WheelFR",     unit: "km/h", min: 0,     max: 200,  freq: 10  },
  { channel: "CAN0", id: "0x200", name: "ABS",            signal: "WheelRL",     unit: "km/h", min: 0,     max: 200,  freq: 10  },
  { channel: "CAN0", id: "0x200", name: "ABS",            signal: "WheelRR",     unit: "km/h", min: 0,     max: 200,  freq: 10  },
  { channel: "CAN0", id: "0x300", name: "Battery",        signal: "Voltage",     unit: "V",    min: 11.5,  max: 14.8, freq: 250 },
  { channel: "CAN0", id: "0x300", name: "Battery",        signal: "Current",     unit: "A",    min: -50,   max: 200,  freq: 250 },
  { channel: "CAN1", id: "0x410", name: "BodyControl",    signal: "FuelLevel",   unit: "%",    min: 10,    max: 100,  freq: 1000},
  { channel: "CAN1", id: "0x410", name: "BodyControl",    signal: "DoorFL",      unit: "",     min: 0,     max: 1,    freq: 5000},
  { channel: "CAN1", id: "0x500", name: "ADAS",           signal: "FrontDist",   unit: "m",    min: 1,     max: 100,  freq: 50  },
  { channel: "CAN1", id: "0x500", name: "ADAS",           signal: "LaneOffset",  unit: "m",    min: -1.5,  max: 1.5,  freq: 30  },
];

const values = {};
SIGNALS.forEach(s => {
  const k = s.channel + s.id + s.signal;
  values[k] = s.min + (s.max - s.min) / 2;
});

function tick(sig) {
  const k = sig.channel + sig.id + sig.signal;
  const range = sig.max - sig.min;
  // Random walk
  let v = values[k] + (Math.random() - 0.5) * range * 0.04;
  v = Math.max(sig.min, Math.min(sig.max, v));
  // Round to reasonable precision
  v = sig.unit === "rpm" || sig.unit === "km/h" ? Math.round(v) :
      sig.unit === ""   ? Math.round(v) :
      parseFloat(v.toFixed(2));
  values[k] = v;

  const msg = {
    channel: sig.channel,
    id: sig.id,
    name: sig.name,
    signal: sig.signal,
    value: v,
    unit: sig.unit,
    timestamp: Date.now() / 1000,
  };
  process.stdout.write(JSON.stringify(msg) + "\n");
}

SIGNALS.forEach(sig => {
  setInterval(() => tick(sig), sig.freq);
});

process.stderr.write("CAN simulator running — pipe to server.js\n");
