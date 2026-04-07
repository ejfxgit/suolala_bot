# NEW BUY ALERT FEATURE
# Monitors SUOLALA token buys on Solana and sends alerts to Telegram

import os
import asyncio
import aiohttp
import json
import time
from datetime import datetime
from typing import Optional, Dict, Set
from dataclasses import dataclass

# ===== CONFIGURATION =====
SUOLALA_MINT = "CY1P83KnKwFYostvjQcoR2HJLyEJWRBRaVQmYyyD3cR8"
WSOL_MINT = "So11111111111111111111111111111111111111112"

# DexScreener pair address for SUOLALA/SOL
DEXSCREENER_PAIR = "79Qaq5b1JfC8bFuXkAvXTR67fRPmMjMVNkEA3bb8bLzi"
DEXSCREENER_API = f"https://api.dexscreener.com/latest/dex/pairs/solana/{DEXSCREENER_PAIR}"

# Solana RPC endpoints
SOLANA_RPC_HTTP = os.getenv("SOLANA_RPC_HTTP", "https://api.mainnet-beta.solana.com")
SOLANA_RPC_WS = os.getenv("SOLANA_RPC_WS", "wss://api.mainnet-beta.solana.com")

# Alert threshold in USD
MIN_BUY_USD = 1000.0

# Auto-delete alert after 3 minutes (180 seconds)
ALERT_DELETE_DELAY = int(os.getenv("ALERT_DELETE_DELAY", "120"))

# Anti-spam: ignore repeated buys from same wallet within this window (seconds)
WALLET_COOLDOWN_SECONDS = 60

# Known DEX program IDs
RAYDIUM_AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
JUPITER_AGGREGATOR_V6 = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"


@dataclass
class TokenData:
    """Live token data from DexScreener"""
    price_usd: float
    market_cap: float
    liquidity_usd: float
    sol_price_usd: float


@dataclass
class BuyTransaction:
    """Parsed buy transaction data"""
    signature: str
    buyer_wallet: str
    sol_amount: float
    token_amount: float
    usd_value: float
    timestamp: int


class BuyAlertMonitor:
    """
    Monitors Solana blockchain for SUOLALA buy transactions.
    Sends alerts to Telegram when buy value exceeds threshold.
    """

    def __init__(self, telegram_bot, chat_ids: list):
        self.bot = telegram_bot
        self.chat_ids = chat_ids
        self.processed_txs: Set[str] = set()
        self.wallet_last_buy: Dict[str, float] = {}
        self.running = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._cached_token_data: Optional[TokenData] = None
        self._token_data_timestamp: float = 0
        self._token_data_cache_ttl = 10  # Cache token data for 10 seconds

    async def start(self):
        """Start the buy alert monitor"""
        self.running = True
        self._session = aiohttp.ClientSession()
        print(f"[BUY ALERT] Starting monitor for SUOLALA: {SUOLALA_MINT}")
        print(f"[BUY ALERT] Minimum buy threshold: ${MIN_BUY_USD} USD")
        
        # Run monitoring loop
        await self._monitor_loop()

    async def stop(self):
        """Stop the buy alert monitor"""
        self.running = False
        if self._session:
            await self._session.close()
            self._session = None
        print("[BUY ALERT] Monitor stopped")

    async def _monitor_loop(self):
        """Main monitoring loop using transaction polling"""
        last_signature = None
        
        while self.running:
            try:
                # Fetch recent transactions for the token
                transactions = await self._get_recent_transactions(last_signature)
                
                for tx in transactions:
                    sig = tx.get("signature")
                    if not sig or sig in self.processed_txs:
                        continue
                    
                    # Parse and check if it's a buy
                    buy_data = await self._parse_transaction(sig)
                    if buy_data and buy_data.usd_value >= MIN_BUY_USD:
                        # Anti-spam check
                        if self._is_wallet_on_cooldown(buy_data.buyer_wallet):
                            print(f"[BUY ALERT] Skipping (wallet cooldown): {buy_data.buyer_wallet}")
                            self.processed_txs.add(sig)
                            continue
                        
                        # Send alert
                        await self._send_alert(buy_data)
                        self.wallet_last_buy[buy_data.buyer_wallet] = time.time()
                    
                    self.processed_txs.add(sig)
                    
                    # Keep processed set bounded
                    if len(self.processed_txs) > 10000:
                        self.processed_txs = set(list(self.processed_txs)[-5000:])
                
                if transactions:
                    last_signature = transactions[0].get("signature")
                
            except Exception as e:
                print(f"[BUY ALERT] Monitor error: {e}")
            
            # Poll interval
            await asyncio.sleep(5)

    async def _get_recent_transactions(self, before_signature: Optional[str] = None) -> list:
        """Fetch recent transactions for the SUOLALA token"""
        if not self._session:
            return []
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [
                SUOLALA_MINT,
                {
                    "limit": 20,
                    "commitment": "confirmed"
                }
            ]
        }
        
        if before_signature:
            payload["params"][1]["before"] = before_signature
        
        try:
            async with self._session.post(
                SOLANA_RPC_HTTP,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("result", [])
        except Exception as e:
            print(f"[BUY ALERT] Failed to fetch transactions: {e}")
        
        return []

    async def _parse_transaction(self, signature: str) -> Optional[BuyTransaction]:
        """Parse a transaction to check if it's a SUOLALA buy"""
        if not self._session:
            return None
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                    "commitment": "confirmed"
                }
            ]
        }
        
        try:
            async with self._session.post(
                SOLANA_RPC_HTTP,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    return None
                
                data = await resp.json()
                result = data.get("result")
                if not result:
                    return None
                
                # Check if transaction was successful
                meta = result.get("meta", {})
                if meta.get("err") is not None:
                    return None
                
                # Check if it involves a DEX swap
                if not self._is_dex_swap(result):
                    return None
                
                # Parse the swap details
                return await self._extract_buy_details(result, signature)
                
        except Exception as e:
            print(f"[BUY ALERT] Failed to parse transaction {signature}: {e}")
        
        return None

    def _is_dex_swap(self, tx_data: dict) -> bool:
        """Check if transaction is a DEX swap (Raydium or Jupiter)"""
        try:
            message = tx_data.get("transaction", {}).get("message", {})
            account_keys = message.get("accountKeys", [])
            
            # Check for DEX program IDs
            for account in account_keys:
                pubkey = account.get("pubkey") if isinstance(account, dict) else account
                if pubkey in [RAYDIUM_AMM_V4, JUPITER_AGGREGATOR_V6]:
                    return True
            
            # Also check inner instructions for Jupiter aggregated swaps
            meta = tx_data.get("meta", {})
            inner_instructions = meta.get("innerInstructions", [])
            for inner in inner_instructions:
                for ix in inner.get("instructions", []):
                    program_id = ix.get("programId")
                    if program_id in [RAYDIUM_AMM_V4, JUPITER_AGGREGATOR_V6]:
                        return True
            
        except Exception:
            pass
        
        return False

    async def _extract_buy_details(self, tx_data: dict, signature: str) -> Optional[BuyTransaction]:
        """Extract buy details from a swap transaction"""
        try:
            meta = tx_data.get("meta", {})
            
            # Get pre and post token balances
            pre_balances = meta.get("preTokenBalances", [])
            post_balances = meta.get("postTokenBalances", [])
            
            # Find SUOLALA token balance changes
            suolala_received = 0.0
            buyer_wallet = None
            
            for post in post_balances:
                if post.get("mint") == SUOLALA_MINT:
                    post_amount = float(post.get("uiTokenAmount", {}).get("uiAmount") or 0)
                    owner = post.get("owner")
                    
                    # Find corresponding pre-balance
                    pre_amount = 0.0
                    for pre in pre_balances:
                        if pre.get("mint") == SUOLALA_MINT and pre.get("owner") == owner:
                            pre_amount = float(pre.get("uiTokenAmount", {}).get("uiAmount") or 0)
                            break
                    
                    change = post_amount - pre_amount
                    if change > suolala_received:
                        suolala_received = change
                        buyer_wallet = owner
            
            # If no SUOLALA received, not a buy
            if suolala_received <= 0 or not buyer_wallet:
                return None
            
            # Calculate SOL spent from lamport balance changes
            pre_sol = meta.get("preBalances", [])
            post_sol = meta.get("postBalances", [])
            
            message = tx_data.get("transaction", {}).get("message", {})
            account_keys = message.get("accountKeys", [])
            
            sol_spent = 0.0
            for i, account in enumerate(account_keys):
                pubkey = account.get("pubkey") if isinstance(account, dict) else account
                if pubkey == buyer_wallet and i < len(pre_sol) and i < len(post_sol):
                    # Convert lamports to SOL
                    sol_change = (pre_sol[i] - post_sol[i]) / 1e9
                    if sol_change > 0:
                        sol_spent = sol_change
                    break
            
            # If we couldn't determine SOL spent, try to estimate from token data
            if sol_spent <= 0:
                token_data = await self._get_token_data()
                if token_data and token_data.price_usd > 0:
                    # Estimate SOL from token amount and price
                    usd_value = suolala_received * token_data.price_usd
                    sol_spent = usd_value / token_data.sol_price_usd if token_data.sol_price_usd > 0 else 0
            
            # Get current token data for USD calculation
            token_data = await self._get_token_data()
            if not token_data:
                return None
            
            usd_value = sol_spent * token_data.sol_price_usd
            
            # Sanity check - if USD value seems wrong, recalculate from token amount
            if usd_value <= 0:
                usd_value = suolala_received * token_data.price_usd
            
            if usd_value <= 0:
                return None
            
            block_time = tx_data.get("blockTime", int(time.time()))
            
            return BuyTransaction(
                signature=signature,
                buyer_wallet=buyer_wallet,
                sol_amount=sol_spent,
                token_amount=suolala_received,
                usd_value=usd_value,
                timestamp=block_time
            )
            
        except Exception as e:
            print(f"[BUY ALERT] Failed to extract buy details: {e}")
        
        return None

    async def _get_token_data(self) -> Optional[TokenData]:
        """Fetch live token data from DexScreener API"""
        # Return cached data if fresh
        if self._cached_token_data and (time.time() - self._token_data_timestamp) < self._token_data_cache_ttl:
            return self._cached_token_data
        
        if not self._session:
            return None
        
        try:
            async with self._session.get(
                DEXSCREENER_API,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return self._cached_token_data
                
                data = await resp.json()
                pair = data.get("pair")
                if not pair:
                    return self._cached_token_data
                
                price_usd = float(pair.get("priceUsd", 0))
                
                # Get market cap (FDV)
                fdv = pair.get("fdv")
                market_cap = float(fdv) if fdv else 0
                
                # Get liquidity
                liquidity = pair.get("liquidity", {})
                liquidity_usd = float(liquidity.get("usd", 0)) if liquidity else 0
                
                # Get SOL price from the pair's quote token
                price_native = float(pair.get("priceNative", 0))
                sol_price_usd = price_usd / price_native if price_native > 0 else 0
                
                # If SOL price seems wrong, fetch it separately
                if sol_price_usd <= 0 or sol_price_usd > 1000:
                    sol_price_usd = await self._get_sol_price()
                
                self._cached_token_data = TokenData(
                    price_usd=price_usd,
                    market_cap=market_cap,
                    liquidity_usd=liquidity_usd,
                    sol_price_usd=sol_price_usd
                )
                self._token_data_timestamp = time.time()
                
                return self._cached_token_data
                
        except Exception as e:
            print(f"[BUY ALERT] Failed to fetch token data: {e}")
        
        return self._cached_token_data

    async def _get_sol_price(self) -> float:
        """Fetch SOL price in USD"""
        if not self._session:
            return 0
        
        try:
            # Use DexScreener SOL/USDC pair
            async with self._session.get(
                "https://api.dexscreener.com/latest/dex/pairs/solana/8sLbNZoA1cfnvMJLPfp98ZLAnFSYCFApfJKMbiXNLwxj",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pair = data.get("pair")
                    if pair:
                        return float(pair.get("priceUsd", 0))
        except Exception:
            pass
        
        return 0

    def _is_wallet_on_cooldown(self, wallet: str) -> bool:
        """Check if wallet is on cooldown to prevent spam"""
        last_buy = self.wallet_last_buy.get(wallet, 0)
        return (time.time() - last_buy) < WALLET_COOLDOWN_SECONDS

    async def _send_alert(self, buy: BuyTransaction):
        """Send buy alert to Telegram"""
        token_data = await self._get_token_data()
        if not token_data:
            print(f"[BUY ALERT] Skipping alert - no token data available")
            return
        
        # Format the alert message (clean, no links, no web preview)
        short_wallet = f"{buy.buyer_wallet[:4]}...{buy.buyer_wallet[-4:]}"
        
        message = (
            f"🟢 SUOLALA BUY\n\n"
            f"💰 Buy Size: ${buy.usd_value:,.2f} USD / {buy.sol_amount:.4f} SOL\n"
            f"👤 Buyer: {short_wallet}\n"
            f"📈 Price: ${token_data.price_usd:.10f}\n"
            f"🏦 MCap: ${token_data.market_cap:,.0f}\n"
            f"💧 Liquidity: ${token_data.liquidity_usd:,.0f}\n\n"
            f"Don't miss the chance 🚀"
        )
        
        # Send to all configured chat IDs
        for chat_id in self.chat_ids:
            try:
                # Send photo with caption
                with open("buy.png", "rb") as photo:
                    sent_msg = await self.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo,
                        caption=message
                    )
                
                print(f"[BUY ALERT] Sent alert for ${buy.usd_value:.2f} buy to chat {chat_id}")
                
                # Schedule auto-delete
                if ALERT_DELETE_DELAY > 0:
                    asyncio.create_task(self._delete_after_delay(sent_msg, ALERT_DELETE_DELAY))
                
            except Exception as e:
                print(f"[BUY ALERT] Failed to send alert to {chat_id}: {e}")

    async def _delete_after_delay(self, message, delay: int):
        """Delete message after specified delay"""
        await asyncio.sleep(delay)
        try:
            await message.delete()
            print(f"[BUY ALERT] Auto-deleted alert message")
        except Exception as e:
            print(f"[BUY ALERT] Failed to delete message: {e}")


# Global monitor instance
_monitor: Optional[BuyAlertMonitor] = None


async def start_buy_alert_monitor(bot, chat_ids: list):
    """Start the buy alert monitor with the given bot and chat IDs"""
    global _monitor
    
    if _monitor is not None:
        print("[BUY ALERT] Monitor already running")
        return
    
    _monitor = BuyAlertMonitor(bot, chat_ids)
    asyncio.create_task(_monitor.start())


async def stop_buy_alert_monitor():
    """Stop the buy alert monitor"""
    global _monitor
    
    if _monitor:
        await _monitor.stop()
        _monitor = None
