# main.py
import uasyncio as asyncio
from tasks.modem_task import modem_loop

async def main():
    await modem_loop()

asyncio.run(main())
