from web3 import Web3
from web3.middleware import (
    simple_cache_middleware,
    http_retry_request_middleware,
)
import json
import math

w3 = Web3(Web3.HTTPProvider("https://arbitrum-one.public.blastapi.io"))
w3.middleware_onion.add(simple_cache_middleware)
w3.middleware_onion.add(http_retry_request_middleware)

with open("./pool.json") as data:
    pool_abi = json.load(data)


with open("./quoter.json") as data:
    quoter_abi = json.load(data)  # Quoter V2 abi


with open("./erc20.json") as data:
    erc20_abi = json.load(data)


with open("./nfpManager.json") as data:
    nfpManager_abi = json.load(data)


with open("./factory.json") as data:
    factory_abi = json.load(data)


quoter_address = "0xAA20EFF7ad2F523590dE6c04918DaAE0904E3b20"  # Quoter V2
quoter = w3.eth.contract(address=quoter_address, abi=quoter_abi)
nfp_manager_address = "0xAA277CB7914b7e5514946Da92cb9De332Ce610EF"
nfp_manager = w3.eth.contract(address=nfp_manager_address, abi=nfpManager_abi)
factory_address = "0xAA2cd7477c451E703f3B9Ba5663334914763edF8"
factory = w3.eth.contract(address=factory_address, abi=factory_abi)


def tick_to_sqrtPriceX96(tick):
    return int(1.0001 ** (tick / 2) * 2**96)


def sqrtPriceX96_to_price(sqrtPrice):
    return (sqrtPrice / 2**96) ** 2


def calc_swap(pool_address, tick_upper, tick_lower, amount, zero_for_one):
    pool = w3.eth.contract(address=pool_address, abi=pool_abi)
    slot0 = pool.functions.slot0().call()
    spacing = pool.functions.tickSpacing().call()
    liquidity = pool.functions.liquidity().call()
    fee = 10**6 / (10**6 - pool.functions.fee().call())

    token0 = w3.eth.contract(address=pool.functions.token0().call(), abi=erc20_abi)
    token1 = w3.eth.contract(address=pool.functions.token1().call(), abi=erc20_abi)
    decimals0 = token0.functions.decimals().call()
    decimals1 = token1.functions.decimals().call()

    multiplier = decimals0 - decimals1

    tick_upper = tick_upper // spacing * spacing
    tick_lower = tick_lower // spacing * spacing

    sqrtPriceX96_upper = tick_to_sqrtPriceX96(tick_upper)
    sqrtPriceX96_lower = tick_to_sqrtPriceX96(tick_lower)

    current_price = sqrtPriceX96_to_price(slot0[0])
    price_upper = sqrtPriceX96_to_price(sqrtPriceX96_upper) * 10**multiplier
    price_lower = sqrtPriceX96_to_price(sqrtPriceX96_lower) * 10**multiplier

    amount0 = amount if zero_for_one else 0
    amount1 = 0 if zero_for_one else amount

    a = (
        amount0
        + (liquidity / math.sqrt(current_price))
        - ((fee * liquidity) / math.sqrt(price_upper))
    )
    b = (
        (fee * liquidity)
        - liquidity
        - (math.sqrt(price_lower) * amount0)
        - ((liquidity * math.sqrt(price_lower)) / math.sqrt(current_price))
        + (amount1 / math.sqrt(price_upper))
        + ((fee * liquidity * math.sqrt(current_price)) / math.sqrt(price_upper))
    )
    c = (
        (liquidity * math.sqrt(price_lower))
        - amount1
        - (fee * liquidity * math.sqrt(current_price))
    )

    target_price = (-b + math.sqrt(b**2 - (4 * a * c))) / (2 * a)
    fee = pool.functions.fee().call()
    sqrtPriceAfter = 0
    low = 0
    high = amount
    amount = amount // 2

    while sqrtPriceAfter != target_price:
        params = {
            "tokenIn": token0.address if zero_for_one else token1.address,
            "tokenOut": token1.address if zero_for_one else token0.address,
            "amountIn": int(amount),
            "fee": fee,
            "sqrtPriceLimitX96": 0,
        }
        result = quoter.functions.quoteExactInputSingle(params).call()
        sqrtPriceAfter = result[1] / 2**96
        if zero_for_one:
            if sqrtPriceAfter < target_price:
                high = amount  # -1
            elif sqrtPriceAfter > target_price:
                low = amount  # + 1
        else:
            if sqrtPriceAfter < target_price:
                low = amount  # + 1
            elif sqrtPriceAfter > target_price:
                high = amount  # - 1

        amount = (low + high) // 2

    return target_price, amount


def calc_compound(token_id):
    position_info = nfp_manager.functions.positions(token_id).call()
    token0 = w3.eth.contract(address=position_info[2], abi=erc20_abi)
    token1 = w3.eth.contract(address=position_info[3], abi=erc20_abi)
    fee = position_info[4]

    amount0 = token0.functions.balanceOf(
        "0x00b7bB87840eeC266fb6388eDdADCa60B40965af"
    ).call()
    amount1 = token1.functions.balanceOf(
        "0x00b7bB87840eeC266fb6388eDdADCa60B40965af"
    ).call()

    pool_address = factory.functions.getPool(token0.address, token1.address, fee).call()
    pool = w3.eth.contract(address=pool_address, abi=pool_abi)
    slot0 = pool.functions.slot0().call()
    liquidity = pool.functions.liquidity().call()
    fee = 10**6 / (10**6 - fee)

    decimals0 = token0.functions.decimals().call()
    decimals1 = token1.functions.decimals().call()

    multiplier = decimals0 - decimals1

    tick_upper = position_info[6]
    tick_lower = position_info[5]

    sqrtPriceX96_upper = tick_to_sqrtPriceX96(tick_upper)
    sqrtPriceX96_lower = tick_to_sqrtPriceX96(tick_lower)

    current_price = sqrtPriceX96_to_price(slot0[0])
    price_upper = sqrtPriceX96_to_price(sqrtPriceX96_upper) * 10**multiplier
    price_lower = sqrtPriceX96_to_price(sqrtPriceX96_lower) * 10**multiplier

    num = math.sqrt(current_price) - math.sqrt(price_lower)
    den = 1 / math.sqrt(current_price) - 1 / math.sqrt(price_upper)
    ratio = den / num
    current_ratio = amount0 / amount1
    zero_for_one = True if current_ratio > ratio else False

    amount = amount0 if zero_for_one else amount1

    a = (
        amount0
        + (liquidity / math.sqrt(current_price))
        - ((fee * liquidity) / math.sqrt(price_upper))
    )
    b = (
        (fee * liquidity)
        - liquidity
        - (math.sqrt(price_lower) * amount0)
        - ((liquidity * math.sqrt(price_lower)) / math.sqrt(current_price))
        + (amount1 / math.sqrt(price_upper))
        + ((fee * liquidity * math.sqrt(current_price)) / math.sqrt(price_upper))
    )
    c = (
        (liquidity * math.sqrt(price_lower))
        - amount1
        - (fee * liquidity * math.sqrt(current_price))
    )

    target_price = (-b + math.sqrt(b**2 - (4 * a * c))) / (2 * a)
    fee = pool.functions.fee().call()
    sqrtPriceAfter = 0
    low = 0
    high = amount
    amount = amount // 2
    while sqrtPriceAfter != target_price:
        params = {
            "tokenIn": token0.address if zero_for_one else token1.address,
            "tokenOut": token1.address if zero_for_one else token0.address,
            "amountIn": int(amount),
            "fee": fee,
            "sqrtPriceLimitX96": 0,
        }
        result = quoter.functions.quoteExactInputSingle(params).call()
        sqrtPriceAfter = result[1] / 2**96
        if zero_for_one:
            if sqrtPriceAfter < target_price:
                high = amount - 1
            elif sqrtPriceAfter > target_price:
                low = amount + 1
        else:
            if sqrtPriceAfter < target_price:
                low = amount + 1
            elif sqrtPriceAfter > target_price:
                high = amount - 1

        amount = (low + high) // 2

    return zero_for_one, math.floor(amount)


print(calc_compound(7803))
