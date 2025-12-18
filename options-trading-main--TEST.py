"""
Options Trading Microservice with Interactive Brokers
Analyzes options Greeks and executes trades based on breakout signals
Uses ib_async library (modern replacement for ib_insync)
"""

import asyncio
import nest_asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd
import numpy as np
from dataclasses import dataclass
from ib_async import IB, Stock, Option, MarketOrder, LimitOrder, util, Forex
import yaml
# from dotenv import load_dotenv
# from pathlib import Path
#
# load_dotenv()

nest_asyncio.apply()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ------------------------------------------------- #
# SET RUNTIME CONFIG VARIABLES
# ------------------------------------------------- #
OPTIONS_TRADER_CONFIG_FILE_FULL_PATH = "config/options-trader-config.yaml"


@dataclass
class TradingConfig:
    """Configuration for trading parameters"""
    watchlist: List[str]
    historical_days: int
    paper_trading: bool
    ib_host: str
    ib_port: int
    ib_client_id: int

    # Greeks thresholds for breakout detection
    min_gamma: float
    min_delta: float
    max_delta: float
    min_vega: float
    min_theta: float
    min_iv_percentile: float
    max_iv_percentile: float

    # Risk management
    max_trades_per_day: int
    require_confirmation: bool


class OptionsDataFetcher:
    """Fetches options data from Interactive Brokers"""

    def __init__(self, ib: IB, config: TradingConfig):
        self.ib = ib
        self.config = config

    async def get_option_chains(self, symbol: str, expiration_days: int = 0) -> List[Option]:
        """
        Fetch option chains for a symbol
        expiration_days=0 means 0DTE options
        """
        try:
            # ib = IB()
            # await ib.connectAsync('127.0.0.1', 4004, clientId=1)
            # await ib.connectAsync('127.0.0.1', 4002, clientId=1)
            # ib.connect('127.0.0.1', 4002, clientId=1)
            ## Define a basic contract object
            # contract = Forex('EURUSD')

            # # Create stock contract
            stock = Stock(symbol, 'SMART', 'USD')
            # qual_contract = await self.ib.qualifyContractsAsync(stock)
            # # qual_contract = self.ib.qualifyContracts(contract)
            # logging.info(f"Qualifying contract: {qual_contract}")
            stock_list = await self.ib.qualifyContractsAsync(stock)

            logger.info(f"Fetching option chains for {stock_list}")

            # Get option chains
            chains = self.ib.reqSecDefOptParams(
                stock.symbol, '', stock.secType, stock.conId
                # stock.symbol, '', 'STK', stock.conId
                # stock_list[0].symbol, '', stock_list[0].secType, stock_list[0].conId
                # stock_list[0].symbol, '', 'FUT', stock_list[0].conId
            )

            # logging.info(f"Found option chains for {chains}")
            df_chains = util.df(chains)
            logging.info(f"Fetched option chains for {df_chains.head(n=10)}")

            if not chains:
                logger.warning(f"No option chains found for {symbol}")
                return []

            # Filter for desired expiration
            target_date = datetime.now().date() + timedelta(days=expiration_days)
            logger.info(f"Fetching option chains for date: [{target_date}]")

            options = []
            for chain in chains:

                logging.info(f"Starting FETCH for [{chain.exchange}] option chains for [[ {chain.tradingClass} ]]")

                # Filter expirations
                expirations = [exp for exp in chain.expirations
                             if abs((datetime.strptime(exp, '%Y%m%d').date() - target_date).days) <= 1]

                if not expirations:
                    continue

                expiration = expirations[0]

                # Get strikes around current price
                # LIVE DATA
                # ticker = self.ib.reqMktData(stock)
                # # ticker = self.ib.reqMktData(stock, '', False, False, [])
                # HISTORICAL DATA - TESTING/using without paid market data subscription
                bar_data = self.ib.reqHistoricalData(stock, f"20251218 20:00:00 US/Eastern", "1 D", "1 hour", "TRADES",1, 1, False, [])
                await asyncio.sleep(5)  # Wait for price data

                logging.info(f"Here is the TICKER INFO: {bar_data}")

                df_qualified = util.df(bar_data)  # pd.DataFrame.from_records(qualified)
                df_qualified.to_csv("df_qualified_output.csv", index=False)
                logging.info(f"df_qualified: \n {df_qualified.head(n=10)}")

                # if not ticker.last or np.isnan(ticker.last):
                #     continue
                #
                # current_price = ticker.last

                if not bar_data[0].close or np.isnan(bar_data[0].close):
                    continue

                # current_price = bar_data.last
                current_price = bar_data[0].close
                open_price = bar_data[0].open
                low_price = bar_data[0].low
                high_price = bar_data[0].high

                # Select strikes within 10% of current price
                strikes = [s for s in chain.strikes
                          # if current_price * 0.9 <= s <= current_price * 1.1]
                           if current_price * 0.9 <= s <= current_price * 1.1]

                # logging.info(f"Strikes: {strikes}")

                # Create option contracts (both calls and puts)
                for strike in strikes[:10]:  # Limit to 10 strikes
                    for right in ['C', 'P']:
                        # logging.info(f"Strike >>> [{strike}]")
                        option = Option(
                            symbol, expiration, strike, right,
                            # chain.exchange, tradingClass=chain.tradingClass
                            "SMART", tradingClass=chain.tradingClass
                            # , secType="OPT"
                            # # , secType=chain.secType
                        )
                        # logging.info(f"Fetching option chain for strike: [{strike}]")
                        # logging.info(f"Option: [ {option} ]")
                        options.append(option)

            # # Assuming 'qualified_contracts_list' contains multiple contracts
            # target_exchange = 'NYSE'
            # # Filter the list using list comprehension
            # filtered_list = [
            #     c for c in qualified_contracts_list if c.primaryExchange == target_exchange
            # ]
            # # Use the desired contract from the filtered results
            # if filtered_list:
            #     selected_contract = filtered_list[0]
            #     print(f"Selected contract on {target_exchange}: {selected_contract}")
            # else:
            #     print(f"No contract found for {target_exchange}")


            df_options = util.df(options)
            df_options.to_csv("df_options_output.csv", index=False)
            logging.info(f"df_options: \n {df_options.info(verbose=True)}")
            logging.info(f"df_options: \n {df_options.head(n=10)}")

            # Qualify contracts
            qualified = self.ib.qualifyContracts(*options)
            logger.info(f"Found {len(qualified)} options for {symbol}")
            # logging.info(f"Qualified Output: [{qualified}]")
            #
            return qualified

        except Exception as e:
            logger.error(f"Error fetching options for {symbol}: {e}")
            return []

    async def get_option_data(self, options: List[Option]) -> pd.DataFrame:
        """Fetch market data and Greeks for options"""
        data = []

        for option_contract_asset in options:
            try:
                # # Request market data with Greeks
                # self.ib.reqMktData(option, '', False, False)
                # self.ib.reqMktData(option_contract_asset, '', False, False)
                self.ib.reqHistoricalData(option_contract_asset, f"20251215 11:00:00 US/Eastern", "1 D", "1 hour", "TRADES",1, 1, False, [])
                await asyncio.sleep(0.5)  # Rate limiting

                # ticker = self.ib.ticker(option)
                ticker = self.ib.ticker(option_contract_asset)

                # Wait for Greeks to populate
                for _ in range(10):
                    if ticker.modelGreeks:
                        break
                    await asyncio.sleep(0.5)

                if not ticker.modelGreeks:
                    continue

                greeks = ticker.modelGreeks

                data.append({
                    'symbol': option_contract_asset.symbol,
                    'expiration': option_contract_asset.lastTradeDateOrContractMonth,
                    'strike': option_contract_asset.strike,
                    'right': option_contract_asset.right,
                    'bid': ticker.bid if ticker.bid and not np.isnan(ticker.bid) else 0,
                    'ask': ticker.ask if ticker.ask and not np.isnan(ticker.ask) else 0,
                    'last': ticker.last if ticker.last and not np.isnan(ticker.last) else 0,
                    'volume': ticker.volume if ticker.volume else 0,
                    'delta': greeks.delta,
                    'gamma': greeks.gamma,
                    'vega': greeks.vega,
                    'theta': greeks.theta,
                    'impl_vol': greeks.impliedVol if greeks.impliedVol else 0,
                    'contract': option_contract_asset
                })

            except Exception as e:
                logger.error(f"Error getting data for {option_contract_asset}: {e}")
                continue

        df = util.df(data)
        df.to_csv("options_greek_output.csv", index=False)
        logging.info(f"Options greeks output -->>> {df.info(verbose=True)}")
        logging.info(f"Options greeks output -->>> {df.head(n=10)}")
        logger.info(f"Collected data for {len(df)} options")

        return df

    async def get_historical_iv(self, symbol: str, days: int) -> Dict[str, float]:
        """Calculate historical IV percentiles"""
        try:
            stock = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(stock)

            end_date = datetime.now()
            bars = self.ib.reqHistoricalData(
                stock,
                endDateTime=end_date,
                durationStr=f'{days} D',
                barSizeSetting='1 day',
                whatToShow='OPTION_IMPLIED_VOLATILITY',
                useRTH=True
            )

            if not bars:
                return {'iv_percentile': 50, 'current_iv': 0}

            ivs = [bar.close for bar in bars if bar.close > 0]

            if not ivs:
                return {'iv_percentile': 50, 'current_iv': 0}

            current_iv = ivs[-1]
            percentile = (sum(1 for iv in ivs if iv < current_iv) / len(ivs)) * 100

            return {
                'iv_percentile': percentile,
                'current_iv': current_iv,
                'iv_rank': percentile
            }

        except Exception as e:
            logger.error(f"Error calculating historical IV for {symbol}: {e}")
            return {'iv_percentile': 50, 'current_iv': 0}


class BreakoutAnalyzer:
    """Analyzes options data for breakout signals"""

    def __init__(self, config: TradingConfig):
        self.config = config

    def analyze_options(self, df: pd.DataFrame, iv_data: Dict) -> pd.DataFrame:
        """
        Analyze options for breakout potential
        Returns filtered dataframe with high-probability setups
        """
        if df.empty:
            return df

        # Calculate mid price
        df['mid_price'] = (df['bid'] + df['ask']) / 2

        # Filter by Greeks thresholds
        signals = df[
            (df['gamma'].abs() >= self.config.min_gamma) &
            (df['delta'].abs() >= self.config.min_delta) &
            (df['delta'].abs() <= self.config.max_delta) &
            (df['vega'].abs() >= self.config.min_vega) &
            (df['theta'] <= self.config.min_theta) &
            (df['volume'] > 0) &
            (df['mid_price'] > 0)
        ]

        # ----------------------------------------------------------------------- #
        # WRITE dataframe to local for review
        # ----------------------------------------------------------------------- #
        if not signals.empty:
            file_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            signals.to_csv(f"daily_signals_data_{file_timestamp}.csv", index=False)
            logger.info(f"Saved signals data to daily_signals_data_{file_timestamp}.csv")
        # ----------------------------------------------------------------------- #

        # IV filter
        current_iv_pct = iv_data.get('iv_percentile', 50)
        if not (self.config.min_iv_percentile <= current_iv_pct <= self.config.max_iv_percentile):
            logger.info(f"IV percentile {current_iv_pct:.1f} outside target range")
            return pd.DataFrame()

        if signals.empty:
            logger.info("No options meet breakout criteria")
            return signals

        # Calculate breakout score (weighted combination of Greeks)
        signals['breakout_score'] = (
            signals['gamma'].abs() * 40 +
            (1 - signals['delta'].abs()) * 20 +  # Favor OTM options
            signals['vega'].abs() * 20 +
            signals['theta'].abs() * 10 +
            signals['volume'] / signals['volume'].max() * 10
        )

        # Sort by score
        signals = signals.sort_values('breakout_score', ascending=False)

        logger.info(f"Found {len(signals)} potential breakout opportunities")

        return signals


class TradeExecutor:
    """Handles trade execution with confirmation and risk management"""

    def __init__(self, ib: IB, config: TradingConfig):
        self.ib = ib
        self.config = config
        self.trades_today = 0
        self.trade_log = []

    def get_user_confirmation(self, trade_info: Dict) -> tuple[bool, int]:
        """Get user confirmation for trade execution"""
        print("\n" + "="*60)
        print("TRADE OPPORTUNITY DETECTED")
        print("="*60)
        print(f"Symbol: {trade_info['symbol']}")
        print(f"Type: {trade_info['right']} (Call/Put)")
        print(f"Strike: ${trade_info['strike']:.2f}")
        print(f"Expiration: {trade_info['expiration']}")
        print(f"Mid Price: ${trade_info['mid_price']:.2f}")
        print(f"\nGreeks:")
        print(f"  Delta: {trade_info['delta']:.4f}")
        print(f"  Gamma: {trade_info['gamma']:.4f}")
        print(f"  Vega: {trade_info['vega']:.4f}")
        print(f"  Theta: {trade_info['theta']:.4f}")
        print(f"  IV: {trade_info['impl_vol']:.2%}")
        print(f"\nBreakout Score: {trade_info['breakout_score']:.2f}")
        print("="*60)

        if not self.config.require_confirmation:
            contracts = int(input("\nEnter number of contracts (0 to skip): "))
            return True, contracts

        response = input("\nExecute this trade? (yes/no): ").strip().lower()

        if response == 'yes':
            contracts = int(input("Enter number of contracts: "))
            return True, contracts

        return False, 0

    async def execute_trade(self, option: Option, quantity: int, trade_info: Dict) -> Optional[str]:
        """Execute option trade"""
        try:
            # Create market order
            action = 'BUY'  # Can be extended for selling
            order = MarketOrder(action, quantity)

            # Place order
            trade = self.ib.placeOrder(option, order)

            # Wait for fill
            await asyncio.sleep(2)

            status = trade.orderStatus.status

            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'symbol': option.symbol,
                'strike': option.strike,
                'right': option.right,
                'expiration': option.lastTradeDateOrContractMonth,
                'quantity': quantity,
                'status': status,
                'trade_info': trade_info
            }

            self.trade_log.append(log_entry)
            self.trades_today += 1

            logger.info(f"Trade executed: {action} {quantity} {option.symbol} "
                       f"{option.strike}{option.right} - Status: {status}")

            return status

        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            return None

    def can_trade(self) -> bool:
        """Check if we can still trade today"""
        if self.trades_today >= self.config.max_trades_per_day:
            logger.warning(f"Max trades per day ({self.config.max_trades_per_day}) reached")
            return False
        return True


class OptionsTradingService:
    """Main trading service orchestrator"""

    def __init__(self, config_path: str = OPTIONS_TRADER_CONFIG_FILE_FULL_PATH):
        self.config = self._load_config(config_path)
        self.ib = IB()
        self.fetcher = None
        self.analyzer = None
        self.executor = None

    def _load_config(self, config_path: str) -> TradingConfig:
        """Load configuration from YAML file"""
        with open(config_path, 'r') as f:
            config_dict = yaml.load(f, Loader=yaml.SafeLoader)

        return TradingConfig(**config_dict)

    async def connect(self):
        """Connect to Interactive Brokers"""
        try:
            # Allow environment variables to override config
            ib_host = os.getenv('IB_HOST', self.config.ib_host)
            ib_port = int(os.getenv('IB_PORT', self.config.ib_port))

            logger.info(f"Attempting to connect to IB Gateway at {ib_host}:{ib_port}")

            await self.ib.connectAsync(
                ib_host,
                ib_port,
                clientId=self.config.ib_client_id
            )

            logger.info(f"✓ Connected to IB Gateway at {ib_host}:{ib_port}")
            logger.info(f"Trading Mode: {'PAPER' if self.config.paper_trading else 'LIVE'}")

            self.fetcher = OptionsDataFetcher(self.ib, self.config)
            self.analyzer = BreakoutAnalyzer(self.config)
            self.executor = TradeExecutor(self.ib, self.config)

        except Exception as e:
            logger.error(f"Failed to connect to IB Gateway: {e}")
            logger.error(f"Make sure IB Gateway is running and accessible at {ib_host}:{ib_port}")
            raise

    async def scan_and_trade(self):
        """Main trading loop - scan for opportunities and execute"""
        logger.info("Starting options scan...")

        for symbol in self.config.watchlist:
            logger.info(f"Analyzing {symbol}...")

            try:
                # Get 0DTE options
                options = await self.fetcher.get_option_chains(symbol, expiration_days=0)

                if not options:
                    continue

                # Get options data with Greeks
                df = await self.fetcher.get_option_data(options)

                if df.empty:
                    continue

                # Get historical IV data
                iv_data = await self.fetcher.get_historical_iv(
                    symbol,
                    self.config.historical_days
                )

                # Analyze for breakouts
                signals = self.analyzer.analyze_options(df, iv_data)

                if signals.empty:
                    continue

                # Process top opportunities
                for idx, row in signals.head(3).iterrows():
                    if not self.executor.can_trade():
                        break

                    trade_info = row.to_dict()

                    # Get user confirmation
                    confirmed, quantity = self.executor.get_user_confirmation(trade_info)

                    if confirmed and quantity > 0:
                        status = await self.executor.execute_trade(
                            row['contract'],
                            quantity,
                            trade_info
                        )

                        if status:
                            print(f"\n✓ Trade executed successfully - Status: {status}")

            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue

    async def run(self):
        """Run the trading service"""
        try:
            await self.connect()

            print("\n" + "="*60)
            print("OPTIONS TRADING MICROSERVICE STARTED")
            print("="*60)
            print(f"Mode: {'PAPER TRADING' if self.config.paper_trading else 'LIVE TRADING'}")
            print(f"Watchlist: {', '.join(self.config.watchlist)}")
            print(f"Historical Days: {self.config.historical_days}")
            print("="*60 + "\n")

            await self.scan_and_trade()

            print("\n" + "="*60)
            print("SCAN COMPLETE")
            print(f"Trades executed: {self.executor.trades_today}")
            print("="*60)

        except Exception as e:
            logger.error(f"Error in trading service: {e}")
            raise
        finally:
            self.ib.disconnect()
            logger.info("Disconnected from IB")


async def main():
    """Main entry point"""
    service = OptionsTradingService(OPTIONS_TRADER_CONFIG_FILE_FULL_PATH)
    await service.run()


if __name__ == '__main__':
    asyncio.run(main())