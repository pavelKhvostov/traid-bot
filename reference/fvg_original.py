import pandas as pd
from datetime import timedelta, datetime
import time
import schedule
import pytz
import os
import random
import json
from typing import Optional, List, Dict, Tuple

# Настройки
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'AVAXUSDT', 'LINKUSDT']
TIMEFRAMES = ['1d', '4h', '1h', '15m']
BASE_DIR = 'data'  # Папка для сохранения данных
SIGNALS_DIR = 'signals'  # Папка для сигналов
TIMEZONE = pytz.timezone('Europe/Moscow')  # Часовой пояс Москвы
ANALYZE_INTERVAL_MINUTES = 5  # Как часто проводить анализ (в минутах)
NEW_SIGNALS_FILE = 'new_signals.json'  # Файл с новыми сигналами в JSON


ENTRY_RANGE = (-0.001, -0.015)


class SignalGenerator:
    @staticmethod
    def generate_tp_sl(prev_open: float, fvg_type: str) -> Dict[str, float]:
        """Генерирует уровни входа, TP и SL с RR 2.2-2.5 и SL 1.5-2.5%"""
        # Генерация параметров
        sl_percent = random.uniform(0.015, 0.025)  # 1.5% - 2.5%
        rr_ratio = random.uniform(2.2, 2.5)  # Risk/Reward ratio

        # Определяем диапазон входа в зависимости от типа FVG
        if fvg_type == "LONG":
            entry_percent = random.uniform(*ENTRY_RANGE)
            entry_price = prev_open * (1 + entry_percent)
            sl_price = entry_price * (1 - sl_percent)
            tp_price = entry_price + (entry_price - sl_price) * rr_ratio
        else:  # SHORT
            entry_percent = random.uniform(0.001, 0.015)  # +0.1% - +1.5% для SHORT
            entry_price = prev_open * (1 + entry_percent)
            sl_price = entry_price * (1 + sl_percent)
            tp_price = entry_price - (sl_price - entry_price) * rr_ratio

        return {
            'entry_price': round(entry_price, 2),
            'sl_price': round(sl_price, 2),
            'tp_price': round(tp_price, 2),
            'rr_ratio': round(rr_ratio, 2)
        }

    @staticmethod
    def create_signal_json(symbol: str, fvg_1h_date: datetime, prev_open: float,
                           fvg_type: str) -> Dict:
        """Создает JSON-запись для нового сигнала"""
        tp_sl = SignalGenerator.generate_tp_sl(prev_open, fvg_type)

        signal_type = "FVG_LONG" if fvg_type == "LONG" else "FVG_SHORT"

        # Форматирование описания
        character_desc = (
            f"Взвешенный RR - {tp_sl['rr_ratio']} | "
            f"Вход - {tp_sl['entry_price']} | "
            f"TP - {tp_sl['tp_price']} ({abs((tp_sl['tp_price'] / tp_sl['entry_price'] - 1) * 100):.2f}%) | "
            f"SL - {tp_sl['sl_price']} ({abs((tp_sl['sl_price'] / tp_sl['entry_price'] - 1) * 100):.2f}%)"
        )

        return {
            "symbol": symbol,
            "pattern": signal_type,
            "timestamp": fvg_1h_date.isoformat(),
            "character": character_desc,
            "entry_price": tp_sl['entry_price'],
            "tp_price": tp_sl['tp_price'],
            "sl_price": tp_sl['sl_price'],
            "rr_ratio": tp_sl['rr_ratio'],
            "fvg_type": fvg_type,
            "sl_percent": abs((tp_sl['sl_price'] / tp_sl['entry_price'] - 1) * 100),
            "tp_percent": abs((tp_sl['tp_price'] / tp_sl['entry_price'] - 1) * 100)
        }

    @staticmethod
    def save_new_signals(new_signals: List[Dict]):
        """Сохраняет новые сигналы в JSON файл (дополняет существующие)"""
        if not new_signals:
            return

        os.makedirs(SIGNALS_DIR, exist_ok=True)
        output_path = os.path.join(SIGNALS_DIR, NEW_SIGNALS_FILE)

        # Загружаем существующие сигналы
        existing_signals = []
        if os.path.exists(output_path):
            with open(output_path, 'r', encoding='utf-8') as f:
                existing_signals = json.load(f)

        # Добавляем только новые уникальные сигналы
        existing_timestamps = {s['timestamp'] for s in existing_signals}
        unique_new_signals = [
            s for s in new_signals
            if s['timestamp'] not in existing_timestamps
        ]

        if not unique_new_signals:
            return

        # Объединяем и сохраняем
        all_signals = existing_signals + unique_new_signals
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(all_signals, f, ensure_ascii=False, indent=2)

        print(f"\nДобавлено {len(unique_new_signals)} новых сигналов в {output_path}")


class FVGAnalyzer:
    @staticmethod
    def load_data_from_csv(filename: str, symbol: str) -> pd.DataFrame:
        """Загрузка данных из CSV файла и преобразование в нужный формат"""
        try:
            df = pd.read_csv(filename)
            df = df.rename(columns={
                'Open time': 'datetime',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            })
            df['datetime'] = pd.to_datetime(df['datetime'])
            df['symbol'] = symbol
            return df
        except Exception as e:
            print(f"Ошибка загрузки данных из {filename}: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    def find_fvg_4h(df_4h: pd.DataFrame) -> pd.DataFrame:
        """Поиск LONG FVG на 4H таймфрейме (high[i-2] < low[i])"""
        fvg_list = []
        if len(df_4h) < 3:
            return pd.DataFrame(fvg_list)

        for i in range(2, len(df_4h)):
            if df_4h['high'].iloc[i - 2] < df_4h['low'].iloc[i]:
                fvg = {
                    'fvg_time': df_4h['datetime'].iloc[i],
                    'high_prev2': df_4h['high'].iloc[i - 2],
                    'low_current': df_4h['low'].iloc[i],
                    'confirmed_time': None,
                    'is_valid': True,
                    'symbol': df_4h['symbol'].iloc[0],
                    'timeframe': '4h',
                    'type': 'LONG'
                }
                fvg_list.append(fvg)
        return pd.DataFrame(fvg_list)

    @staticmethod
    def find_short_fvg_4h(df_4h: pd.DataFrame) -> pd.DataFrame:
        """Поиск SHORT FVG на 4H таймфрейме (low[i-2] > high[i])"""
        fvg_list = []
        if len(df_4h) < 3:
            return pd.DataFrame(fvg_list)

        for i in range(2, len(df_4h)):
            if df_4h['low'].iloc[i - 2] > df_4h['high'].iloc[i]:
                fvg = {
                    'fvg_time': df_4h['datetime'].iloc[i],
                    'low_prev2': df_4h['low'].iloc[i - 2],
                    'high_current': df_4h['high'].iloc[i],
                    'confirmed_time': None,
                    'is_valid': True,
                    'symbol': df_4h['symbol'].iloc[0],
                    'timeframe': '4h',
                    'type': 'SHORT'
                }
                fvg_list.append(fvg)
        return pd.DataFrame(fvg_list)

    @staticmethod
    def validate_fvg(fvg_df: pd.DataFrame, df_4h: pd.DataFrame) -> pd.DataFrame:
        """Универсальная проверка условий валидации FVG (LONG и SHORT)"""
        valid_fvg = []

        for _, fvg in fvg_df.iterrows():
            mask = df_4h['datetime'] == fvg['fvg_time']
            if not mask.any():
                continue

            start_idx = df_4h[mask].index[0]
            found = False
            fvg_type = fvg.get('type', 'LONG')

            for i in range(start_idx + 1, len(df_4h)):
                if fvg_type == 'LONG':
                    # Логика валидации для LONG FVG
                    if df_4h['low'].iloc[i] <= fvg['low_current']:
                        if df_4h['close'].iloc[i] > fvg['high_prev2']:
                            fvg['confirmed_time'] = df_4h['datetime'].iloc[i]
                            valid_fvg.append(fvg)
                            found = True
                            break
                        else:
                            found = True
                            break
                else:
                    # Логика валидации для SHORT FVG
                    if df_4h['high'].iloc[i] >= fvg['high_current']:
                        if df_4h['close'].iloc[i] < fvg['low_prev2']:
                            fvg['confirmed_time'] = df_4h['datetime'].iloc[i]
                            valid_fvg.append(fvg)
                            found = True
                            break
                        else:
                            found = True
                            break

            if not found:
                valid_fvg.append(fvg)

        return pd.DataFrame(valid_fvg)

    @staticmethod
    def find_first_1h_fvg_in_window(valid_fvg_4h: pd.DataFrame, df_1h: pd.DataFrame) -> pd.DataFrame:
        """Поиск ПЕРВОГО FVG 1H (LONG или SHORT) в течение 8 часов после подтверждения"""
        results = []

        for _, fvg in valid_fvg_4h.iterrows():
            if pd.isna(fvg['confirmed_time']) or fvg['confirmed_time'] is None:
                continue

            start_time = fvg['confirmed_time']
            end_time = start_time + timedelta(hours=8)
            fvg_type = fvg.get('type', 'LONG')

            window = df_1h[(df_1h['datetime'] >= start_time) & (df_1h['datetime'] <= end_time)]

            for i in range(3, len(window)):
                if fvg_type == 'LONG':
                    # Условие для LONG FVG 1H
                    if window['high'].iloc[i - 3] < window['low'].iloc[i - 1]:
                        results.append(FVGAnalyzer._create_result_record(fvg, window, i - 1, i - 3, 'LONG'))
                        break
                else:
                    # Условие для SHORT FVG 1H
                    if window['low'].iloc[i - 3] > window['high'].iloc[i - 1]:
                        results.append(FVGAnalyzer._create_result_record(fvg, window, i - 1, i - 3, 'SHORT'))
                        break

        return pd.DataFrame(results)

    @staticmethod
    def _create_result_record(fvg, window, current_idx, prev_idx, fvg_type):
        """Создание записи результата"""
        base_data = {
            'symbol': window['symbol'].iloc[0],
            'fvg_4h_time': fvg['fvg_time'],
            'fvg_4h_confirmed_time': fvg['confirmed_time'],
            'fvg_1h_time': window['datetime'].iloc[current_idx],
            'window_start': fvg['confirmed_time'],
            'window_end': fvg['confirmed_time'] + timedelta(hours=8),
            'type': fvg_type
        }

        if fvg_type == 'LONG':
            base_data.update({
                'fvg_4h_high_prev2': fvg['high_prev2'],
                'fvg_4h_low_current': fvg['low_current'],
                'fvg_1h_high_prev2': window['high'].iloc[prev_idx],
                'fvg_1h_low_current': window['low'].iloc[current_idx],
                'prev_open': window['close'].iloc[current_idx]  # Добавляем цену открытия свечи
            })
        else:
            base_data.update({
                'fvg_4h_low_prev2': fvg['low_prev2'],
                'fvg_4h_high_current': fvg['high_current'],
                'fvg_1h_low_prev2': window['low'].iloc[prev_idx],
                'fvg_1h_high_current': window['high'].iloc[current_idx],
                'prev_open': window['close'].iloc[current_idx]  # Добавляем цену открытия свечи
            })

        return base_data

    @staticmethod
    def is_today(date: datetime) -> bool:
        """Проверяет, относится ли дата к сегодняшнему дню"""
        today = datetime.now(TIMEZONE).date()
        return date.date() == today

    @staticmethod
    def analyze_symbol(symbol: str) -> List[Dict]:
        """Полный анализ FVG для одного символа с генерацией сигналов"""
        print(f"\nАнализируем {symbol}...")

        # Загрузка данных
        df_4h = FVGAnalyzer.load_data_from_csv(f'{BASE_DIR}/{symbol}_4h_ohlc.csv', symbol)
        df_1h = FVGAnalyzer.load_data_from_csv(f'{BASE_DIR}/{symbol}_1h_ohlc.csv', symbol)

        if df_4h.empty or df_1h.empty:
            print(f"Не удалось загрузить данные для {symbol}")
            return []

        # Поиск и валидация FVG
        long_fvg = FVGAnalyzer.find_fvg_4h(df_4h)
        short_fvg = FVGAnalyzer.find_short_fvg_4h(df_4h)

        valid_long = FVGAnalyzer.validate_fvg(long_fvg, df_4h)
        valid_short = FVGAnalyzer.validate_fvg(short_fvg, df_4h)

        # Поиск FVG 1H в окнах
        long_results = FVGAnalyzer.find_first_1h_fvg_in_window(valid_long, df_1h)
        short_results = FVGAnalyzer.find_first_1h_fvg_in_window(valid_short, df_1h)

        # Фильтрация только сегодняшних сигналов
        today_long = [r for _, r in long_results.iterrows()
                      if FVGAnalyzer.is_today(r['fvg_1h_time'])]
        today_short = [r for _, r in short_results.iterrows()
                       if FVGAnalyzer.is_today(r['fvg_1h_time'])]

        # Подготовка сигналов для сохранения
        signals = []
        for result in today_long:
            signals.append({
                'symbol': symbol,
                'fvg_1h_time': result['fvg_1h_time'],
                'prev_open': result['prev_open'],
                'fvg_type': 'LONG'
            })

        for result in today_short:
            signals.append({
                'symbol': symbol,
                'fvg_1h_time': result['fvg_1h_time'],
                'prev_open': result['prev_open'],
                'fvg_type': 'SHORT'
            })

        # Сохранение результатов в CSV
        if not long_results.empty:
            output_file = f'{BASE_DIR}/{symbol}_3.1_LONG.csv'
            if os.path.exists(output_file):
                existing = pd.read_csv(output_file)
                long_results = pd.concat([existing, long_results]).drop_duplicates()
            long_results.to_csv(output_file, index=False)

        if not short_results.empty:
            output_file = f'{BASE_DIR}/{symbol}_3.1_SHORT.csv'
            if os.path.exists(output_file):
                existing = pd.read_csv(output_file)
                short_results = pd.concat([existing, short_results]).drop_duplicates()
            short_results.to_csv(output_file, index=False)

        return signals


def run_analysis():
    """Запуск анализа для всех символов"""
    print(f"\n=== Запуск анализа в {datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')} ===")

    all_signals = []
    for symbol in SYMBOLS:
        try:
            signals = FVGAnalyzer.analyze_symbol(symbol)
            if signals:
                print(f"Найдено {len(signals)} новых сигналов для {symbol}")
                all_signals.extend(signals)
            else:
                print(f"Для {symbol} не найдено новых сигналов")
        except Exception as e:
            print(f"Ошибка при анализе {symbol}: {str(e)}")

    # Генерация и сохранение JSON сигналов
    if all_signals:
        json_signals = []
        for signal in all_signals:
            json_signal = SignalGenerator.create_signal_json(
                signal['symbol'],
                signal['fvg_1h_time'],
                signal['prev_open'],
                signal['fvg_type']
            )
            json_signals.append(json_signal)

        SignalGenerator.save_new_signals(json_signals)


def main():
    """Основная функция для запуска в фоновом режиме"""
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(SIGNALS_DIR, exist_ok=True)

    # Настройка расписания
    schedule.every(ANALYZE_INTERVAL_MINUTES).minutes.do(run_analysis)

    # Первый запуск сразу
    run_analysis()

    print("\nСкрипт запущен в фоновом режиме. Поиск FVG паттернов...")
    print(f"Анализ будет выполняться каждые {ANALYZE_INTERVAL_MINUTES} минут.")
    print(f"Новые сигналы дополняются в {SIGNALS_DIR}/{NEW_SIGNALS_FILE}")

    # Бесконечный цикл
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
