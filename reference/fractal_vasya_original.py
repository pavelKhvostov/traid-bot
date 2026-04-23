import pandas as pd
from datetime import datetime, timedelta


def find_valid_fractal_lows_4h(csv_file):
    """Функция для поиска валидных фрактальных минимумов на 4H таймфрейме"""
    try:
        # Пытаемся прочитать файл с заголовками
        try:
            df = pd.read_csv(csv_file)
            expected_columns = ['timestamp', 'open', 'high', 'low', 'close']
            if not all(col in df.columns for col in expected_columns):
                raise ValueError("Columns not in standard format")
        except:
            df = pd.read_csv(csv_file, header=None,
                             names=['timestamp', 'open', 'high', 'low', 'close'])

        # Преобразование типов
        df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df = df.dropna()
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')

        if len(df) < 5:
            raise ValueError("Недостаточно данных")

    except Exception as e:
        print(f"Ошибка при обработке 4H файла: {str(e)}")
        return pd.DataFrame()

    # Поиск фракталов
    fractals = []
    for i in range(2, len(df) - 2):
        current_low = df.loc[i, 'low']
        if (current_low < df.loc[i - 1, 'low'] and
                current_low < df.loc[i - 2, 'low'] and
                current_low < df.loc[i + 1, 'low'] and
                current_low < df.loc[i + 2, 'low']):

            # Ищем свечу, которая снимает фрактал (low < фрактального low)
            for j in range(i + 1, len(df)):
                if current_low > df.loc[j, 'close']:
                    break
                else:
                    if df.loc[j, 'low'] < current_low < df.loc[j, 'close']:
                        fractals.append({
                            'fractal_datetime': df.loc[i, 'datetime'],
                            'fractal_low': current_low,
                            'breaker_datetime': df.loc[j, 'datetime'],
                            'breaker_low': df.loc[j, 'low'],
                            'breaker_close': df.loc[j, 'close'],
                            'breaker_open': df.loc[j, 'open'],
                            'breaker_high': df.loc[j, 'high'],
                            'breaker_index': j
                        })
                        break

    return pd.DataFrame(fractals)


def load_data(file_path, timeframe):
    """Загрузка данных с автоматическим определением формата"""
    try:
        try:
            data = pd.read_csv(file_path)
            expected_columns = ['timestamp', 'open', 'high', 'low', 'close']
            if not all(col in data.columns for col in expected_columns):
                raise ValueError("Columns not in standard format")
        except:
            data = pd.read_csv(file_path, header=None,
                               names=['timestamp', 'open', 'high', 'low', 'close'])

        data['timestamp'] = pd.to_numeric(data['timestamp'], errors='coerce')
        data['datetime'] = pd.to_datetime(data['timestamp'], unit='ms')
        data = data.dropna()
        data = data.sort_values('datetime').reset_index(drop=True)
        data['timeframe'] = timeframe
        return data

    except Exception as e:
        print(f"Ошибка загрузки {timeframe} данных: {str(e)}")
        return None


def is_fractal_low(data, i, lookback=2, lookforward=2):
    """Проверка на фрактальный минимум"""
    if i < lookback or i >= len(data) - lookforward:
        return False
    current_low = data.loc[i, 'low']
    return (current_low < data.loc[i - 1, 'low'] and
            current_low < data.loc[i - 2, 'low'] and
            current_low < data.loc[i + 1, 'low'] and
            current_low < data.loc[i + 2, 'low'])


def find_vasya_fractal(fractals_4h, h1_data):
    """Поиск свечи 'Вася' - фрактала в диапазоне Breaker свечи"""
    vasya_candles = []

    for _, fractal in fractals_4h.iterrows():
        breaker_time = fractal['breaker_datetime']
        breaker_bar = h1_data[h1_data['datetime'] == breaker_time]

        if breaker_bar.empty:
            continue

        breaker_idx = breaker_bar.index[0]
        breaker_low = fractal['breaker_low']
        breaker_close = fractal['breaker_close']

        # Диапазон поиска - от breaker_low до breaker_close
        price_min = min(breaker_low, breaker_close)
        price_max = max(breaker_low, breaker_close)

        # Ищем свечу 'Вася' после breaker свечи
        for i in range(breaker_idx + 4, len(h1_data) - 2):
            current_low = h1_data.loc[i, 'low']
            current_close = h1_data.loc[i, 'close']

            # Проверяем что свеча в диапазоне и close >= breaker_low
            if not (price_min <= current_low <= price_max and current_close >= breaker_low):
                continue

            # Проверяем что это фрактальный минимум
            if is_fractal_low(h1_data, i):
                vasya_candles.append({
                    'fractal_4h_datetime': fractal['fractal_datetime'],
                    'breaker_datetime': fractal['breaker_datetime'],
                    'vasya_datetime': h1_data.loc[i, 'datetime'],
                    'vasya_low': current_low,
                    'vasya_close': current_close,
                    'vasya_index': i
                })
                break  # Берем только первый подходящий фрактал

    return pd.DataFrame(vasya_candles)


def find_confirmation_candle(vasya_df, h1_data):
    """Поиск свечи подтверждения после 'Вася'"""
    confirmations = []

    for _, vasya in vasya_df.iterrows():
        vasya_idx = vasya['vasya_index']
        vasya_low = vasya['vasya_low']
        vasya_close = vasya['vasya_close']
        has_confirmation = False
        has_fractal_high = False

        # Ищем свечу подтверждения после 'Вася'
        for i in range(vasya_idx + 1, len(h1_data)):
            current_low = h1_data.loc[i, 'low']
            current_close = h1_data.loc[i, 'close']

            # Условие остановки - close < vasya_close
            if current_close < vasya_close:
                break

            # Проверяем наличие фрактальной high между 'Вася' и текущей свечой
            if not has_fractal_high:
                for j in range(vasya_idx + 1, i):
                    if j < 2 or j >= len(h1_data) - 2:
                        continue

                    current_high = h1_data.loc[j, 'high']
                    if (current_high > h1_data.loc[j - 1, 'high'] and
                            current_high > h1_data.loc[j - 2, 'high'] and
                            current_high > h1_data.loc[j + 1, 'high'] and
                            current_high > h1_data.loc[j + 2, 'high']):
                        has_fractal_high = True
                        break

            # Условие подтверждения: low < vasya_low и close > vasya_low
            if current_low < vasya_low and current_close > vasya_low and has_fractal_high:
                confirmations.append({
                    'fractal_4h_datetime': vasya['fractal_4h_datetime'],
                    'breaker_datetime': vasya['breaker_datetime'],
                    'vasya_datetime': vasya['vasya_datetime'],
                    'vasya_low': vasya_low,
                    'confirmation_datetime': h1_data.loc[i, 'datetime'],
                    'confirmation_low': current_low,
                    'confirmation_close': current_close,
                    'has_fractal_high': has_fractal_high,
                    'bars_between': i - vasya_idx
                })
                has_confirmation = True
                break

        if not has_confirmation:
            continue

    return pd.DataFrame(confirmations)


def find_fvg_after_confirmation(confirmations, m15_data):
    """Поиск FVG на 15M после свечи подтверждения"""
    fvg_results = []

    for _, confirm in confirmations.iterrows():
        if confirm['confirmation_datetime'] is None:
            continue

        confirm_time = confirm['confirmation_datetime']
        # Берем бары после confirmation_datetime (не включая его)
        m15_after_confirm = m15_data[m15_data['datetime'] > confirm_time]

        if len(m15_after_confirm) < 3:
            continue

        start_idx = m15_after_confirm.index[0]
        first_ob_low = confirm['vasya_low']  # low свечи "Вася"

        # Ищем FVG (high[i-2] < low[i])
        for i in range(start_idx + 2, len(m15_data)):
            if i >= len(m15_data):
                break

            current_candle = m15_data.loc[i]

            # Условие остановки: если close < low свечи "Вася"
            if current_candle['close'] < first_ob_low:
                break

            # Условие FVG для лонга
            high_2 = m15_data.loc[i - 2, 'high']
            low_0 = current_candle['low']

            if high_2 < low_0:
                fvg_results.append({
                    'fractal_4h_datetime': confirm['fractal_4h_datetime'],
                    'vasya_datetime': confirm['vasya_datetime'],
                    'confirmation_datetime': confirm['confirmation_datetime'],
                    'fvg_datetime': current_candle['datetime'],
                    'fvg_type': 'long',
                    'fvg_high': high_2,
                    'fvg_low': low_0,
                    'fvg_size': low_0 - high_2,
                    'fvg_candle_0': f"({current_candle['open']}-{current_candle['close']})",
                    'fvg_candle_2': f"({m15_data.loc[i - 2, 'open']}-{m15_data.loc[i - 2, 'close']})",
                    'stop_condition': current_candle['close'] < first_ob_low
                })
                break  # Ищем только первый FVG

    return pd.DataFrame(fvg_results)


def main():
    # Настройки путей
    fractal_4h_file = 'dist/BTCUSDT_ohlcv_4h.csv'
    hourly_file = 'dist/BTCUSDT_ohlcv_1h.csv'
    m15_file = 'dist/BTCUSDT_ohlcv_15m.csv'

    print("Поиск по новой логике: 4H фрактал -> свеча 'Вася' -> подтверждение -> FVG")

    # Загрузка данных
    fractals_4h = find_valid_fractal_lows_4h(fractal_4h_file)
    if fractals_4h.empty:
        print("Не найдено фракталов на 4H")
        return

    h1_data = load_data(hourly_file, '1h')
    if h1_data is None:
        return

    m15_data = load_data(m15_file, '15m')
    if m15_data is None:
        return

    # 1. Находим свечи 'Вася'
    vasya_df = find_vasya_fractal(fractals_4h, h1_data)
    if vasya_df.empty:
        print("Не найдено свечей 'Вася'")
        return

    # 2. Ищем свечи подтверждения
    confirm_df = find_confirmation_candle(vasya_df, h1_data)

    # 3. Ищем FVG после подтверждения
    fvg_results = find_fvg_after_confirmation(confirm_df, m15_data)

    # Объединяем результаты правильно
    if not fvg_results.empty:
        # Сначала объединяем вася и подтверждения
        vasya_confirm = pd.merge(
            vasya_df,
            confirm_df,
            on=['fractal_4h_datetime', 'breaker_datetime', 'vasya_datetime', 'vasya_low'],
            how='left'
        )

        # Затем объединяем с FVG
        full_results = pd.merge(
            vasya_confirm,
            fvg_results,
            on=['fractal_4h_datetime', 'confirmation_datetime'],
            how='left'
        )

        # Удаляем строки, где есть хотя бы одно пустое значение
        full_results = full_results.dropna()

        # Проверяем, что остались данные после удаления пустых строк
        if not full_results.empty:
            # Выбираем только нужные колонки для вывода
            cols_to_show = [
                'fractal_4h_datetime',
                'vasya_datetime',
                'confirmation_datetime',
                'fvg_datetime',
                'fvg_size'
            ]

            # Проверяем какие колонки действительно существуют
            available_cols = [col for col in cols_to_show if col in full_results.columns]

            print("\nНайденные FVG:")
            print(full_results[available_cols].to_string(index=False))

            # Сохраняем полные результаты (только строки без пустых значений)
            full_results.to_csv('vasya_fvg_results.csv', index=False)
            print("\nРезультаты сохранены в 'vasya_fvg_results.csv'")

            # Статистика
            print(f"\nСтатистика:")
            print(f"Всего свечей 'Вася': {len(vasya_df)}")
            print(f"С подтверждением: {len(confirm_df[confirm_df['confirmation_datetime'].notna()])}")
            print(f"С FVG: {len(fvg_results)}")
            print(f"Полных записей (без пропусков): {len(full_results)}")
        else:
            print("Нет полных записей (все содержат пустые значения)")
    else:
        print("FVG не найдены")


if __name__ == "__main__":
    main()
