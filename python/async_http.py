#! /usr/bin/python
# -*- coding:utf-8 -*-
import aiohttp
import asyncio
import async_timeout
async def test(url):
    async with aiohttp.ClientSession() as session:
         with async_timeout.timeout(10):
            async with session.post(url) as resp:
                r = await resp.text()
                print(r)
                # r = await resp.read()  ## 用于读取字节流，不作解码
                print(resp.headers.get('Content-Type'))
                # TODO: do something...
def test_main():
    tasks = []
    tasks.append(
        asyncio.ensure_future(
            test("http://hostname1.com/xxx")
        )
    )
    tasks.append(
        asyncio.ensure_future(
            test("http://hostname2.com/xxx")
        )
    )
    loop.run_until_complete(asyncio.gather(*tasks))
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    test_main()
    loop.close()
