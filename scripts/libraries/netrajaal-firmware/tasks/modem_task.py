# tasks/modem_task.py
import uasyncio as asyncio
from drivers.modem_spi import SC16IS750
import config

modem = SC16IS750(spi_bus=config.SPI_BUS, cs_pin=config.MODEM_CS_PIN, baudrate=config.BAUDRATE)

async def modem_loop():
    print("Initializing Modem...")
    if modem.ping():
        print("SC16IS750 connected!")

    while True:
        print("Sending AT Command...")
        for b in config.PING_CMD:
            modem.write(b)

        await asyncio.sleep(1)

        print("Reading response:")
        response = ""
        timeout = 20
        while timeout > 0:
            await asyncio.sleep(0.1)
            c = modem.read()
            if c != -1:
                response += chr(c)
            else:
                timeout -= 1
        print("Modem replied:", response)
        await asyncio.sleep(5)
