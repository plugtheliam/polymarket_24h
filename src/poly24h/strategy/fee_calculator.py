"""Polymarket Fee Calculator.

Implements Polymarket's dynamic fee structure:
- Taker Fee: 4 * p * (1-p) * 3.15% (max 3.15% at 50% probability)
- Maker Rebate: 80% of Taker Fee

Used for Paired Entry profitability calculations.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

# Fee constants
TAKER_FEE_MAX_RATE = Decimal("0.0315")  # 3.15% at 50% probability
MAKER_REBATE_RATIO = Decimal("0.80")     # 80% of taker fee


def calculate_taker_fee(price: Decimal) -> Decimal:
    """Calculate Polymarket taker fee for a given price.
    
    Fee formula: fee_rate = 4 * p * (1-p) * max_rate
    
    Args:
        price: Order price (0.0 to 1.0)
    
    Returns:
        Fee rate (not absolute amount)
    
    Examples:
        >>> calculate_taker_fee(Decimal("0.50"))
        Decimal('0.0315')
        >>> calculate_taker_fee(Decimal("0.30"))
        Decimal('0.02646')
    """
    prob = price
    fee_rate = 4 * prob * (1 - prob) * TAKER_FEE_MAX_RATE
    return fee_rate.quantize(Decimal("0.00001"), rounding=ROUND_DOWN)


def calculate_maker_rebate(price: Decimal) -> Decimal:
    """Calculate Polymarket maker rebate for a given price.
    
    Rebate = Taker Fee * 80%
    
    Args:
        price: Order price (0.0 to 1.0)
    
    Returns:
        Rebate rate
    
    Examples:
        >>> calculate_maker_rebate(Decimal("0.50"))
        Decimal('0.0252')
    """
    taker_fee = calculate_taker_fee(price)
    return taker_fee * MAKER_REBATE_RATIO


def calculate_real_cost(price: Decimal, is_maker: bool = False) -> Decimal:
    """Calculate real cost after fees/rebates.
    
    - Taker: price + fee
    - Maker: price - rebate
    
    Args:
        price: Order price (0.0 to 1.0)
        is_maker: True if maker order, False if taker
    
    Returns:
        Real cost including fees/rebates
    
    Examples:
        >>> calculate_real_cost(Decimal("0.50"), is_maker=False)
        Decimal('0.5315')  # Taker pays more
        >>> calculate_real_cost(Decimal("0.50"), is_maker=True)
        Decimal('0.4748')  # Maker pays less
    """
    if is_maker:
        return price - calculate_maker_rebate(price)
    return price + calculate_taker_fee(price)


def calculate_paired_cpp(
    yes_price: Decimal,
    no_price: Decimal,
    yes_is_maker: bool = False,
    no_is_maker: bool = False,
) -> Decimal:
    """Calculate real Cost Per Pair (CPP) after fees/rebates.
    
    CPP = real_cost(YES) + real_cost(NO)
    
    Args:
        yes_price: YES side price
        no_price: NO side price
        yes_is_maker: True if YES order is maker
        no_is_maker: True if NO order is maker
    
    Returns:
        Real CPP including all fees/rebates
    
    Examples:
        >>> # Both taker (worst case)
        >>> calculate_paired_cpp(Decimal("0.45"), Decimal("0.50"))
        Decimal('0.9815...')
        
        >>> # Both maker (best case)
        >>> calculate_paired_cpp(Decimal("0.45"), Decimal("0.50"), True, True)
        Decimal('0.9048...')
    """
    real_yes = calculate_real_cost(yes_price, yes_is_maker)
    real_no = calculate_real_cost(no_price, no_is_maker)
    return real_yes + real_no


def is_profitable_after_fees(
    yes_price: Decimal,
    no_price: Decimal,
    min_margin: Decimal = Decimal("0.01"),
    use_taker: bool = True,
) -> bool:
    """Check if paired entry is profitable after fees.
    
    For paired entry to be profitable:
        CPP < 1.0 - min_margin
    
    Args:
        yes_price: YES side price
        no_price: NO side price
        min_margin: Minimum required margin after fees (default 1%)
        use_taker: Use taker fees (True) or maker rebates (False)
    
    Returns:
        True if profitable after fees
    
    Examples:
        >>> is_profitable_after_fees(Decimal("0.40"), Decimal("0.45"))
        True  # Wide spread, profitable
        
        >>> is_profitable_after_fees(Decimal("0.48"), Decimal("0.50"))
        False  # Tight spread, fees eat margin
    """
    cpp = calculate_paired_cpp(
        yes_price=yes_price,
        no_price=no_price,
        yes_is_maker=not use_taker,
        no_is_maker=not use_taker,
    )
    
    max_cpp = Decimal("1.0") - min_margin
    return cpp < max_cpp


def calculate_expected_profit(
    yes_price: Decimal,
    no_price: Decimal,
    shares: Decimal,
    use_taker: bool = True,
) -> Decimal:
    """Calculate expected profit from paired entry.
    
    Profit = shares * (1.0 - CPP)
    
    Args:
        yes_price: YES side price
        no_price: NO side price
        shares: Number of share pairs
        use_taker: Use taker fees
    
    Returns:
        Expected profit in USD
    """
    cpp = calculate_paired_cpp(
        yes_price=yes_price,
        no_price=no_price,
        yes_is_maker=not use_taker,
        no_is_maker=not use_taker,
    )
    
    margin_per_pair = Decimal("1.0") - cpp
    return shares * margin_per_pair
