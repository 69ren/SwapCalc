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
    tick_upper = tick_upper // spacing * spacing
    tick_lower = tick_lower // spacing * spacing

    sqrtPriceX96_upper = tick_to_sqrtPriceX96(tick_upper)
    sqrtPriceX96_lower = tick_to_sqrtPriceX96(tick_lower)

    token0 = w3.eth.contract(address=pool.functions.token0().call(), abi=erc20_abi)
    token1 = w3.eth.contract(address=pool.functions.token1().call(), abi=erc20_abi)
    decimals0 = token0.functions.decimals().call()
    decimals1 = token1.functions.decimals().call()

    multiplier = decimals0 - decimals1
    fee = pool.functions.fee().call()

    current_price = (sqrtPriceX96_to_price(slot0[0])) * 10**multiplier
    price_upper = (sqrtPriceX96_to_price(sqrtPriceX96_upper)) * 10**multiplier
    price_lower = (sqrtPriceX96_to_price(sqrtPriceX96_lower)) * 10**multiplier
    # Calc ratio of token0:token1 or token1:token0
    a = math.sqrt(current_price) - math.sqrt(price_lower)
    b = 1 / math.sqrt(current_price) - 1 / math.sqrt(price_upper)
    target_ratio = b / a if zero_for_one else a / b
    # amount / ((ratio * price) + 1)
    amount_to_swap = (
        amount / ((target_ratio * current_price) + 1)
        if zero_for_one
        else amount / ((target_ratio * (1 / current_price)) + 1)
    )

    low = 0
    high = amount
    while True:
        quote_params = {
            "tokenIn": token0.address if zero_for_one else token1.address,
            "tokenOut": token1.address if zero_for_one else token0.address,
            "amountIn": int(amount_to_swap),
            "fee": fee,
            "sqrtPriceLimitX96": 0,
        }
        result = quoter.functions.quoteExactInputSingle(quote_params).call()
        amountOut = result[0]
        new_price = sqrtPriceX96_to_price(result[1]) * 10**multiplier
        a = math.sqrt(new_price) - math.sqrt(price_lower)
        b = 1 / math.sqrt(new_price) - 1 / math.sqrt(price_upper)
        actual_ratio = (
            ((amount - amount_to_swap) / amountOut) / 10**multiplier
            if zero_for_one
            else 10**multiplier / (amountOut / (amount - amount_to_swap))
        )
        if actual_ratio == target_ratio:
            return amount_to_swap
        previous_target_ratio = target_ratio
        target_ratio = b / a if zero_for_one else a / b
        if target_ratio == previous_target_ratio:
            return amount_to_swap
        if actual_ratio < target_ratio:
            high = amount_to_swap - 1
        elif actual_ratio > target_ratio:
            low = amount_to_swap + 1
        amount_to_swap = (low + high) // 2


def calc_swap_by_range(pool_address, range, amount, zero_for_one):
    pool = w3.eth.contract(address=pool_address, abi=pool_abi)
    slot0 = pool.functions.slot0().call()
    spacing = pool.functions.tickSpacing().call()

    tick_upper = (
        math.floor(slot0[1] + math.log(1 + range, 1.0001)) // spacing * spacing
    ) + spacing
    tick_lower = math.floor(slot0[1] + math.log(1 - range, 1.0001)) // spacing * spacing
    sqrtPriceX96_upper = tick_to_sqrtPriceX96(tick_upper)
    sqrtPriceX96_lower = tick_to_sqrtPriceX96(tick_lower)
    token0 = w3.eth.contract(address=pool.functions.token0().call(), abi=erc20_abi)
    token1 = w3.eth.contract(address=pool.functions.token1().call(), abi=erc20_abi)
    decimals0 = token0.functions.decimals().call()
    decimals1 = token1.functions.decimals().call()
    multiplier = decimals0 - decimals1
    fee = pool.functions.fee().call()
    current_price = (sqrtPriceX96_to_price(slot0[0])) * 10**multiplier
    price_upper = (sqrtPriceX96_to_price(sqrtPriceX96_upper)) * 10**multiplier
    price_lower = (sqrtPriceX96_to_price(sqrtPriceX96_lower)) * 10**multiplier
    a = math.sqrt(current_price) - math.sqrt(price_lower)
    b = 1 / math.sqrt(current_price) - 1 / math.sqrt(price_upper)
    target_ratio = b / a if zero_for_one else a / b
    amount_to_swap = (
        amount / ((target_ratio * current_price) + 1)
        if zero_for_one
        else amount / ((target_ratio * (1 / current_price)) + 1)
    )
    low = 0
    high = amount
    while True:
        quote_params = {
            "tokenIn": token0.address if zero_for_one else token1.address,
            "tokenOut": token1.address if zero_for_one else token0.address,
            "amountIn": int(amount_to_swap),
            "fee": fee,
            "sqrtPriceLimitX96": 0,
        }
        result = quoter.functions.quoteExactInputSingle(quote_params).call()
        amountOut = result[0]
        new_price = sqrtPriceX96_to_price(result[1]) * 10**multiplier
        a = math.sqrt(new_price) - math.sqrt(price_lower)
        b = 1 / math.sqrt(new_price) - 1 / math.sqrt(price_upper)
        actual_ratio = (
            ((amount - amount_to_swap) / amountOut) / 10**multiplier
            if zero_for_one
            else 10**multiplier / (amountOut / (amount - amount_to_swap))
        )
        if actual_ratio == target_ratio:
            return (amount_to_swap, tick_upper, tick_lower)
        previous_target_ratio = target_ratio
        target_ratio = b / a if zero_for_one else a / b
        if target_ratio == previous_target_ratio:
            return (amount_to_swap, tick_upper, tick_lower)
        if actual_ratio < target_ratio:
            high = amount_to_swap - 1
        elif actual_ratio > target_ratio:
            low = amount_to_swap + 1
        amount_to_swap = (low + high) // 2


def calc_existing_position(amount0, amount1, token_id):
    position_info = nfp_manager.functions.positions(token_id).call()

    token0 = w3.eth.contract(address=position_info[2], abi=erc20_abi)
    token1 = w3.eth.contract(address=position_info[3], abi=erc20_abi)
    fee = position_info[4]

    pool_address = factory.functions.getPool(token0.address, token1.address, fee).call()
    pool = w3.eth.contract(address=pool_address, abi=pool_abi)
    slot0 = pool.functions.slot0().call()

    tick_upper = position_info[6]
    tick_lower = position_info[5]
    sqrtPriceX96_upper = tick_to_sqrtPriceX96(tick_upper)
    sqrtPriceX96_lower = tick_to_sqrtPriceX96(tick_lower)

    decimals0 = token0.functions.decimals().call()
    decimals1 = token1.functions.decimals().call()
    multiplier = decimals0 - decimals1

    zero_for_one = True if amount0 > amount1 else False

    current_price = (sqrtPriceX96_to_price(slot0[0])) * 10**multiplier
    price_upper = (sqrtPriceX96_to_price(sqrtPriceX96_upper)) * 10**multiplier
    price_lower = (sqrtPriceX96_to_price(sqrtPriceX96_lower)) * 10**multiplier
    a = math.sqrt(current_price) - math.sqrt(price_lower)
    b = 1 / math.sqrt(current_price) - 1 / math.sqrt(price_upper)
    target_ratio = b / a if zero_for_one else a / b
    # formula: amountToSwap = (inputBalance - (optimalRatio * outputBalance)) / ((optimalRatio * inputTokenPrice) + 1))
    amount_to_swap = (
        amount0 - (target_ratio * amount1) / ((target_ratio * current_price) + 1)
        if zero_for_one
        else amount1
        - (target_ratio * amount0) / ((target_ratio * (1 / current_price)) + 1)
    )
    low = 0
    high = amount0 if zero_for_one else amount1
    while True:
        quote_params = {
            "tokenIn": token0.address if zero_for_one else token1.address,
            "tokenOut": token1.address if zero_for_one else token0.address,
            "amountIn": int(amount_to_swap),
            "fee": fee,
            "sqrtPriceLimitX96": 0,
        }
        print(quote_params)
        result = quoter.functions.quoteExactInputSingle(quote_params).call()
        amountOut = result[0]
        new_price = sqrtPriceX96_to_price(result[1]) * 10**multiplier

        a = math.sqrt(new_price) - math.sqrt(price_lower)
        b = 1 / math.sqrt(new_price) - 1 / math.sqrt(price_upper)
        actual_ratio = (
            ((amount0 - amount_to_swap) / amountOut) / 10**multiplier
            if zero_for_one
            else 10**multiplier / (amountOut / (amount1 - amount_to_swap))
        )
        if actual_ratio == target_ratio:
            return (amount_to_swap, zero_for_one)
        previous_target_ratio = target_ratio
        target_ratio = b / a if zero_for_one else a / b
        if target_ratio == previous_target_ratio:
            return (amount_to_swap, zero_for_one)
        if actual_ratio < target_ratio:
            high = amount_to_swap - 1
        elif actual_ratio > target_ratio:
            low = amount_to_swap + 1
        amount_to_swap = (low + high) // 2


# print(calc_existing_position(10**18, 0.5*10**18, 7803))

print(
    calc_swap("0x307FeCfc2f14082F9Abe641CD09737B77856b640", -122600, -124800, 10**18, False)
)
