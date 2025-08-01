run_omv = True
try:
    import omv
    print("The 'omv' library IS installed.")
except ImportError:
    print("The 'omv' library IS NOT installed.")
    run_omv = False

if run_omv:
    from machine import RTC, UART
    import uasyncio as asyncio
    import utime
    import sensor
    import ml
    import os                   # file system access
    import image                # image drawing and manipulation
    import time

else:
    import asyncio
    import serial
    import time as utime
    from time import gmtime, strftime
import sys
import random


print_lock = asyncio.Lock()

UART_BAUDRATE = 57600
USBA_BAUDRATE = 57600
MIN_SLEEP = 0.1
ACK_SLEEP = 0.3

MIDLEN = 6
FLAKINESS = 0

FRAME_SIZE = 225


# -------- Start FPS clock -----------
#clock = time.clock()            # measure frame/sec
image_count = 0                 # Counter to keep tranck of saved images

my_addr = None
peer_addr = None

if run_omv:
    rtc = RTC()
    print("Running on device : " + omv.board_id())
    if omv.board_id() == "5D4676E05D4676E05D4676E0":
        my_addr = 'A'
    else:
        print("Unknown device ID for " + omv.board_id())
        sys.exit()
    clock_start = utime.ticks_ms() # get millisecond counter
    UART_PORT = 1
    uart = UART(UART_PORT, baudrate=UART_BAUDRATE, timeout=1000)
    uart.init(UART_BAUDRATE, bits=8, parity=None, stop=1)

    # ------ Configuration for tensorflow model ------
    MODEL_PATH = "/rom/person_detect.tflite"
    model = ml.Model(MODEL_PATH)
    print(" Model loaded:", model)

    IMG_DIR = "/sdcard/images/"
    CONFIDENCE_THRESHOLD = 0.5

    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.HD)  # Use HD resolution
    sensor.skip_frames(time=2000)
else:
    my_addr = 'B'
    USBA_PORT = "/dev/ttyUSB0"
    # USBA_PORT = "/dev/tty.usbserial-0001"
    try:
        uart = serial.Serial(USBA_PORT, USBA_BAUDRATE, timeout=0.1)
    except serial.SerialException as e:
        print(f"[ERROR] Could not open serial port {USBA_PORT}: {e}")
        sys.exit(1)
    clock_start = int(utime.time() * 1000)

shortest_path_to_cc = []
seen_neighbours = []

# ------- Person Detection + snapshot ---------
# TODO(anand): Test with IR lense for person detection in Night
def detect_person(img):
    prediction = model.predict([img])
    scores = zip(model.labels, prediction[0].flatten().tolist())
    scores = sorted(scores, key=lambda x: x[1], reverse=True)  # Highest confidence first
    p_conf = 0.0
    for label, conf in scores:
        if label == "person":
            p_conf = conf
            if conf >= CONFIDENCE_THRESHOLD:
                return (True, p_conf)
    return (False, p_conf)

# ------- Person detection loop ---------
async def person_detection_loop():
    global image_count
    for i in range(5): #    while True:
        img = sensor.snapshot()
        print(len(img.bytearray()))
        image_count += 1
        print(f"Image count: {image_count}")
        person_detected, confidence = detect_person(img)
        if person_detected:
            r = get_rand()
            raw_path = f"{IMG_DIR}raw_{r}_{person_detected}_{confidence:.2f}.jpg"
            print(f"Saving image to {raw_path}")
            img.save(raw_path)
            # Draw visual annotations on the image
            # img.draw_rectangle((0, 0, img.width(), img.height()), color=(255, 0, 0), thickness=2)  # Full image border
            # img.draw_string(4, 4, f"Person: {confidence:.2f}", color=(255, 255, 255), scale=2)      # Label text
            # TODO(anand): As we are have a memory constrain on the sd card(<=2GB), Need to calculate max number of images that can be saved and how images will be deleted after transmission.
            # processed_path = f"{IMG_DIR}/processed_{image_count}.jpg"
            # img.save(processed_path)  # Save image with annotations
        await asyncio.sleep(30)

def get_human_ts():
    if run_omv:
        _,_,_,_,h,m,s,_ = rtc.datetime()
        t=f"{m}:{s}"
    else:
        t = strftime("%M:%S", gmtime())
    return t

def log(msg):
    t = get_human_ts()
    print(f"{t} : {msg}")

msgs_sent = []
msgs_unacked = []
msgs_recd = []

# MSG TYPE = H(eartbeat), A(ck), B(egin), E(nd), N(ack), C(hunk), e(V)ent

def time_msec():
    if run_omv:
        delta = utime.ticks_diff(utime.ticks_ms(), clock_start) # compute time difference
    else:
        delta = int(utime.time() * 1000) - clock_start
    return delta

def get_rand():
    rstr = ""
    for i in range(3):
        rstr += chr(65+random.randint(0,25))
    return rstr

# TypeSourceDestRRRandom
def get_msg_id(msgtype, dest):
    rrr = get_rand()
    mid = f"{msgtype}{my_addr}{dest}{rrr}"
    return mid

def ellepsis(msg):
    if len(msg) > 200:
        return msg[:100] + "......." + msg[-100:]
    return msg

def ack_needed(msgtype):
    if msgtype == "A":
        return False
    if msgtype in ["H", "B", "E"]:
        return True
    return False

def radio_send(data):
    uart.write(data)
    log(f"[SENT ] {data.decode().strip()} at {time_msec()}")

async def send_single_msg(msgtype, msgstr, dest):
    mid = get_msg_id(msgtype, dest)
    datastr = f"{mid};{msgstr}\n"
    ackneeded = dest != "*" and ack_needed(msgtype)
    unackedid = 0
    timesent = time_msec()
    if ackneeded:
        unackedid = len(msgs_unacked)
        msgs_unacked.append((mid, msgstr, timesent))
    else:
        msgs_sent.append((mid, msgstr, timesent))
    if not ackneeded:
        radio_send(datastr.encode())
        return (True, [])
    for retry_i in range(5):
        radio_send(datastr.encode())
        await asyncio.sleep(ACK_SLEEP if ackneeded else MIN_SLEEP)
        for i in range(3):
            at, missing_chunks = ack_time(mid)
            if at > 0:
                log(f"Msg {mid} : was acked in {at - timesent} msecs")
                msgs_sent.append(msgs_unacked.pop(unackedid))
                return (True, missing_chunks)
            else:
                log(f"Still waiting for ack for {mid} # {i}")
                await asyncio.sleep(ACK_SLEEP * (i+1)) # progressively more sleep
        log(f"Failed to get ack for message {mid} for retry # {retry_i}")
    log(f"Failed to send message {mid}")
    return (False, [])

def make_chunks(msg):
    chunks = []
    while len(msg) > 200:
        chunks.append(msg[0:200])
        msg = msg[200:]
    if len(msg) > 0:
        chunks.append(msg)
    return chunks

# === Send Function ===
async def send_msg(msgtype, msgstr, dest):
    if len(msgstr) < FRAME_SIZE:
        succ, _ = await send_single_msg(msgtype, msgstr, dest)
        return succ
    imid = get_rand()
    chunks = make_chunks(msgstr)
    log(f"Chunking {len(msgstr)} long message with id {imid} into {len(chunks)} chunks")
    succ, _ = await send_single_msg("B", f"{msgtype}:{imid}:{len(chunks)}", dest)
    if not succ:
        log(f"Failed sending chunk begin")
        return False
    for i in range(len(chunks)):
        _ = await send_single_msg("I", f"{imid}:{i}:{chunks[i]}", dest)
    for retry_i in range(50):
        succ, missing_chunks = await send_single_msg("E", imid, dest)
        if not succ:
            log(f"Failed sending chunk end")
            break
        if len(missing_chunks) == 1 and missing_chunks[0] == -1:
            log(f"Successfully sent all chunks")
            return True
        log(f"Receiver still missing {len(missing_chunks)} chunks after retry {retry_i}: {missing_chunks}")
        for mc in missing_chunks:
            _, _ = await send_single_msg("I", f"{imid}:{mc}:{chunks[mc]}", dest)
    return False

def ack_time(smid):
    for (rmid, msg, t) in msgs_recd:
        if rmid[0] == "A":
            if smid == msg[:MIDLEN]:
                missingids = []
                if msg[0] == "E" and len(msg) > MIDLEN+1:
                    missingids = [int(i) for i in msg[MIDLEN+1:].split(',')]
                return (t, missingids)
    return (-1, None)

async def log_status():
    await asyncio.sleep(1)
    async with print_lock:
        log("$$$$ %%%%% ###### Printing status ###### $$$$$$ %%%%%%%%")
        log(f"So far sent {len(msgs_sent)} messages and received {len(msgs_recd)} messages")
    ackts = []
    msgs_not_acked = []
    for mid, msg, t in msgs_sent:
        if mid[0] == "A":
            continue
        #log("Getting ackt for " + s + "which was sent at " + str(t))
        ackt, _ = ack_time(mid)
        if ackt > 0:
            time_to_ack = ackt - t
            ackts.append(time_to_ack)
        else:
            msgs_not_acked.append(mid)
    if ackts:
        ackts.sort()
        mid = ackts[len(ackts)//2]
        p90 = ackts[int(len(ackts) * 0.9)]
        async with print_lock:
            log(f"[ACK Times] 50% = {mid:.2f}s, 90% = {p90:.2f}s")
            log(f"So far {len(msgs_not_acked)} messsages havent been acked")
            log(msgs_not_acked)

# === Async Receiver for openmv ===
async def radio_read():
    if run_omv:
        buffer = b""
        while True:
            if uart.any():
                buffer = uart.readline()
                process_message(buffer)
            await asyncio.sleep(0.01)
    else:
        buffer = b""
        while True:
            await asyncio.sleep(0.01)
            while uart.in_waiting > 0:
                byte = uart.read(1)
                if byte == b'\n':
                    process_message(buffer)
                    buffer = b""
                else:
                    buffer += byte

chunk_map = {} # chunk ID to (expected_chunks, [(iter, chunk_data)])

def begin_chunk(msg):
    parts = msg.split(":")
    if len(parts) != 3:
        log(f"ERROR : begin message unparsable {msg}")
        return
    mst = parts[0]
    cid = parts[1]
    numchunks = int(parts[2])
    chunk_map[cid] = (mst, numchunks, [])

def add_chunk(msg):
    parts = msg.split(":")
    if len(parts) != 3:
        log(f"ERROR : add chunk message unparsable {msg}")
        return
    cid = parts[0]
    citer = int(parts[1])
    cdata = parts[2]
    if cid not in chunk_map:
        log(f"ERROR : no entry yet for {cid}")
    chunk_map[cid][2].append((citer, cdata))

def get_data_for_iter(list_chunks, chunkiter):
    for citer, chunk_data in list_chunks:
        if citer == chunkiter:
            return chunk_data
    return None

def get_missing_chunks(cid):
    if cid not in chunk_map:
        #log(f"Should never happen, have no entry in chunk_map for {cid}")
        return []
    mst, expected_chunks, list_chunks = chunk_map[cid]
    missing_chunks = []
    for i in range(expected_chunks):
        if not get_data_for_iter(list_chunks, i):
            missing_chunks.append(i)
    return missing_chunks

def recompile_msg(cid):
    if len(get_missing_chunks(cid)) > 0:
        return None
    if cid not in chunk_map:
        #log(f"Should never happen, have no entry in chunk_map for {cid}")
        return []
    mst, expected_chunks, list_chunks = chunk_map[cid]
    recompiled = ""
    for i in range(expected_chunks):
        recompiled += get_data_for_iter(list_chunks, i)
    # Ignoring message type for now
    return recompiled

def clear_chunkid(cid):
    if cid in chunk_map:
        chunk_map.pop(cid)

# Note only sends as many as wouldnt go beyond frame size
# Assumption is that subsequent end chunks would get the rest
def end_chunk(msg):
    cid = msg
    missing = get_missing_chunks(cid)
    log(f"I am missing {len(missing)} chunks : {missing}")
    if len(missing) > 0:
        missing_str = str(missing[0])
        for i in range(1, len(missing)):
            if len(missing_str) + len(str(missing[i])) + 1 + MIDLEN + MIDLEN < FRAME_SIZE:
                missing_str += "," + str(missing[i])
        return (False, missing_str)
    else:
        recompiled = recompile_msg(cid)
        clear_chunkid(msg)
        return (True, recompiled)

def parse_header(data):
    if len(data) < 8:
        return None
    mid = data[:MIDLEN].decode()
    mst = mid[0]
    sender = mid[1]
    receiver = mid[2]
    for i in range(MIDLEN):
        if (mid[i] < 'A' or mid[i] > 'Z') and (i == 3 and mid[i] == "*"):
            return None
    if chr(data[MIDLEN]) != ';':
        return None
    msg = data[7:].decode().strip()
    return (mid, mst, sender, receiver, msg)

def hb_process(mid, msg):
    # if cc stats
    # if intermediate forward. asyncio.create
    pass

def img_process(mid, msg):
    # if intermediate forward. asyncio.create
    # if cc stats
    pass

def scan_process(mid, msg):
    print(msg)
    if msg not in seen_neighbours:
        seen_neighbours.append(msg)

def spath_process(mid, msg):
    if not run_omv:
        print(f"Ignoting shortest path since I am cc")
        return
    if len(msg) == 0:
        print(f"Empty spath")
        return
    spath = msg.split(",")
    if my_addr in spath:
        print(f"Cyclic, ignoring")
        return
    if len(shortest_path_to_cc) == 0 or len(shortest_path_to_cc) > len(spath):
        print(f"Updating spath from {shortest_path_to_cc} to {spath}")
        shortest_path_to_cc = spath
    for n in seen_neighbours:
        nmsg = my_addr + "," + shortest_path_to_cc
        asyncio.create_task(send_msg("S", nmsg, n))

def process_message(data):
    parsed = parse_header(data)
    if not parsed:
        log(f"Failure parsing incoming data : {data}")
        return
    if random.randint(1,100) <= FLAKINESS:
        log(f"Flakiness dropping {data}")
        return
    mid, mst, sender, receiver, msg = parsed
    if receiver != "*" and my_addr != receiver:
        log(f"Skipping message as it is not for me but for {receiver} : {mid}")
        return
    log(f"[RECV ] MID: {mid}: {msg} at {time_msec()}")
    msgs_recd.append((mid, msg, time_msec()))
    ackmessage = mid
    if mst == "H":
        hb_process(mid, msg)
    if mst == "B":
        begin_chunk(msg)
    elif mst == "I":
        add_chunk(msg)
    elif mst == "E":
        alldone, retval = end_chunk(msg)
        if alldone:
            ackmessage += ":-1"
            log(f"Alldone, Len={len(retval)}, Data={ellepsis(retval)}")
        else:
            ackmessage += f":{retval}"
    if ack_needed(mst) and receiver != "*":
        asyncio.create_task(send_msg("A", ackmessage, sender))

async def send_long_message():
    peer_addr = "B"
    long_string = ""
    for i in range(500):
        long_string += "_0123456789"
    i = 0
    for i in range(1): #while True: 
        i = i + 1
        if i > 0 and i % 10 == 0:
            asyncio.create_task(log_status())
        msg = f"MSG-{i}-{long_string}"
        await send_msg("H", msg, peer_addr)
        await asyncio.sleep(2)

async def send_heartbeat():
    while True:
        hb = f"{my_addr}:{get_human_ts()}"
        if len(shortest_path_to_cc) > 0:
            peer_addr = shortest_path_to_cc[0]
            await send_msg("H", hb, peer_addr)
        await asyncio.sleep(30)

import constants

async def send_scan():
    while True:
        scanmsg = constants.msg
        #scanmsg = "HCONST"
        #f"{my_addr}"
        await send_msg("N", scanmsg, "*")
        await asyncio.sleep(10) # reduce after setup

async def send_spath():
    while True:
        sp = f"{my_addr}"
        for n in seen_neighbours:
            await send_msg("S", sp, n)
        await asyncio.sleep(300)

async def main():
    log(f"[INFO] Started device {my_addr} listening for {peer_addr}")
    asyncio.create_task(radio_read())
    if run_omv:
        asyncio.create_task(send_heartbeat())
        asyncio.create_task(send_scan())
        # asyncio.create_task(person_detection_loop())
        # asyncio.create_task(send_long_message())
        await asyncio.sleep(36000)
    else:
        asyncio.create_task(send_scan())
        asyncio.create_task(send_spath())
        await asyncio.sleep(3600000)

try:
    asyncio.run(main())
except KeyboardInterrupt:
    log("Stopped.")
