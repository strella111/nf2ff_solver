# -*- coding: utf-8 -*-
"""Загрузка результатов режима «Измерение лучей АФАР» (Beam№*.xlsx + scan_params.json).

Выделено из excel_module.py основного проекта — только функция-загрузчик.
"""

import os
import json

import numpy as np
from loguru import logger
from openpyxl import load_workbook
from typing import Optional


def load_beam_pattern_results(save_dir: str) -> Optional[dict]:
    """
    Загружает результаты измерения лучей из Excel файлов для досканирования
    
    Args:
        save_dir: Путь к папке с результатами (base_dir/luchi/{дата})
        
    Returns:
        dict: {
            'beams': [список лучей],
            'freq_list': [список частот],
            'data': {beam_num: {freq: {'x': [...], 'y': [...], 'amp': [[...]], 'phase': [[...]]}}},
            'x_list': [список координат X],
            'y_list': [список координат Y],
            'step_x': шаг по X,
            'step_y': шаг по Y
        } или None при ошибке
    """
    try:
        if not os.path.exists(save_dir):
            logger.error(f"Папка не найдена: {save_dir}")
            return None

        params_file = os.path.join(save_dir, 'scan_params.json')
        loaded_params = None
        if os.path.exists(params_file):
            try:
                with open(params_file, 'r', encoding='utf-8') as f:
                    loaded_params = json.load(f)
                logger.info(f"Загружены параметры сканирования из {params_file}")
            except Exception as e:
                logger.warning(f"Не удалось загрузить параметры сканирования: {e}")
        
        # Находим все файлы Beam№*.xlsx
        beam_files = []
        for filename in os.listdir(save_dir):
            if filename.startswith('Beam№') and filename.endswith('.xlsx'):
                try:
                    beam_num = int(filename.replace('Beam№', '').replace('.xlsx', ''))
                    beam_files.append((beam_num, os.path.join(save_dir, filename)))
                except ValueError:
                    continue
        
        if not beam_files:
            logger.warning(f"Не найдено файлов лучей в {save_dir}")
            return None
        
        beam_files.sort(key=lambda x: x[0])  # Сортируем по номеру луча
        
        # Используем параметры из JSON, если есть, иначе определяем из файлов
        if loaded_params:
            beams = loaded_params.get('beams', [beam_num for beam_num, _ in beam_files])
            freq_list = loaded_params.get('freq_list', [])
            x_list = loaded_params.get('x_list', [])
            y_list = loaded_params.get('y_list', [])
            step_x = loaded_params.get('step_x', 1.0)
            step_y = loaded_params.get('step_y', 1.0)
        else:
            beams = [beam_num for beam_num, _ in beam_files]
            freq_list = []
            x_list = []
            y_list = []
            step_x = 1.0
            step_y = 1.0
        
        # Загружаем данные из первого файла для определения структуры
        first_beam_num, first_file = beam_files[0]
        workbook = load_workbook(first_file)
        sheet = workbook.active
        
        # Если частоты не загружены из JSON, определяем из файла
        if not freq_list:
            # Ищем все частоты
            row = 1
            while row <= sheet.max_row:
                cell = sheet.cell(row, 1)
                if cell.value == 'Frequency':
                    freq_cell = sheet.cell(row, 2)
                    if freq_cell.value:
                        try:
                            freq = float(freq_cell.value)
                            freq_list.append(freq)
                        except (ValueError, TypeError):
                            pass
                row += 1
            
            if not freq_list:
                logger.error("Не найдено частот в файле")
                return None
        
        # Определяем размеры данных из первой частоты
        first_freq_row = None
        for row in range(1, sheet.max_row + 1):
            if sheet.cell(row, 1).value == 'Frequency' and sheet.cell(row, 2).value == freq_list[0]:
                first_freq_row = row
                break
        
        if first_freq_row is None:
            logger.error("Не найдена первая частота в файле")
            return None
        
        # Находим размер данных (количество столбцов с данными)
        magnitude_row = first_freq_row + 1
        max_col = 0
        for col in range(1, sheet.max_column + 1):
            cell = sheet.cell(magnitude_row + 1, col)  # Первая строка данных
            if cell.value is not None:
                max_col = max(max_col, col)
        
        len_y = max_col  # Количество столбцов = количество Y координат
        
        # Находим количество строк данных (до следующего Frequency или до конца)
        next_freq_row = None
        for row in range(first_freq_row + 1, sheet.max_row + 1):
            if sheet.cell(row, 1).value == 'Frequency':
                next_freq_row = row
                break
        
        if next_freq_row:
            # size_freq_data = 3 + len_x * 2
            # next_freq_row = first_freq_row + size_freq_data
            # len_x = (next_freq_row - first_freq_row - 3) // 2
            len_x = (next_freq_row - first_freq_row - 3) // 2
        else:
            # Последняя частота - считаем до конца
            phase_start_row = None
            for row in range(first_freq_row + 1, sheet.max_row + 1):
                if sheet.cell(row, 1).value == 'Phase':
                    phase_start_row = row
                    break
            if phase_start_row:
                # phase_start_row = first_freq_row + 3 + len_x
                len_x = phase_start_row - first_freq_row - 3
            else:
                # Если не нашли Phase, используем общую формулу
                len_x = (sheet.max_row - first_freq_row - 3) // 2
        
        size_freq_data = 3 + len_x * 2
        
        # Если координаты не загружены из JSON, используем индексы
        if not x_list:
            x_list = list(range(len_x))
        if not y_list:
            y_list = list(range(len_y))
        
        # Загружаем данные для всех лучей
        data = {}
        for beam_num, file_path in beam_files:
            workbook = load_workbook(file_path)
            sheet = workbook.active
            data[beam_num] = _read_sheet_data(
                sheet, freq_list, len_x, len_y, size_freq_data, x_list, y_list)

        logger.info(f"Загружены данные: {len(beams)} лучей, {len(freq_list)} частот, {len_x}x{len_y} точек")
        
        result = {
            'beams': beams,
            'freq_list': freq_list,
            'data': data,
            'x_list': x_list,
            'y_list': y_list,
            'step_x': step_x,
            'step_y': step_y,
            'save_dir': save_dir
        }
        
        # Добавляем параметры из JSON, если они были загружены
        if loaded_params:
            result['left_x'] = loaded_params.get('left_x')
            result['right_x'] = loaded_params.get('right_x')
            result['up_y'] = loaded_params.get('up_y')
            result['down_y'] = loaded_params.get('down_y')
            # Добавляем настройки PNA и синхронизатора
            result['pna_settings'] = loaded_params.get('pna_settings')
            result['sync_settings'] = loaded_params.get('sync_settings')
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при загрузке результатов измерения лучей: {e}", exc_info=True)
        return None


def _detect_freqs(sheet) -> list:
    """Список частот из листа (ячейки «Frequency» в первом столбце)."""
    freqs = []
    for row in range(1, sheet.max_row + 1):
        if sheet.cell(row, 1).value == 'Frequency':
            v = sheet.cell(row, 2).value
            try:
                freqs.append(float(v))
            except (TypeError, ValueError):
                pass
    return freqs


def _detect_layout(sheet, freq_list) -> Optional[tuple]:
    """Размеры данных листа: (len_x, len_y, size_freq_data).

    Логика та же, что и в load_beam_pattern_results: один блок частоты —
    это 3 строки заголовков + len_x строк амплитуды + len_x строк фазы.
    """
    first_freq_row = None
    for row in range(1, sheet.max_row + 1):
        if sheet.cell(row, 1).value == 'Frequency' and sheet.cell(row, 2).value == freq_list[0]:
            first_freq_row = row
            break
    if first_freq_row is None:
        logger.error("Не найдена первая частота в файле")
        return None

    magnitude_row = first_freq_row + 1
    len_y = 0
    for col in range(1, sheet.max_column + 1):
        if sheet.cell(magnitude_row + 1, col).value is not None:
            len_y = max(len_y, col)

    next_freq_row = None
    for row in range(first_freq_row + 1, sheet.max_row + 1):
        if sheet.cell(row, 1).value == 'Frequency':
            next_freq_row = row
            break

    if next_freq_row:
        len_x = (next_freq_row - first_freq_row - 3) // 2
    else:
        phase_start_row = None
        for row in range(first_freq_row + 1, sheet.max_row + 1):
            if sheet.cell(row, 1).value == 'Phase':
                phase_start_row = row
                break
        if phase_start_row:
            len_x = phase_start_row - first_freq_row - 3
        else:
            len_x = (sheet.max_row - first_freq_row - 3) // 2

    size_freq_data = 3 + len_x * 2
    return len_x, len_y, size_freq_data


def _read_sheet_data(sheet, freq_list, len_x, len_y, size_freq_data, x_list, y_list) -> dict:
    """Прочитать амплитуду и фазу по всем частотам с одного листа.

    Returns: {freq: {'x', 'y', 'amp', 'phase'}}.
    """
    data = {}
    for freq_idx, freq in enumerate(freq_list):
        row_start = freq_idx * size_freq_data + 1
        amp_2d = np.full((len_y, len_x), np.nan)
        phase_2d = np.full((len_y, len_x), np.nan)

        for x_idx in range(len_x):
            for y_idx in range(len_y):
                cell = sheet.cell(row_start + 2 + x_idx, y_idx + 1)
                if cell.value is not None:
                    try:
                        amp_2d[y_idx, x_idx] = float(cell.value)
                    except (ValueError, TypeError):
                        pass

        for x_idx in range(len_x):
            for y_idx in range(len_y):
                cell = sheet.cell(row_start + 3 + len_x + x_idx, y_idx + 1)
                if cell.value is not None:
                    try:
                        phase_2d[y_idx, x_idx] = float(cell.value)
                    except (ValueError, TypeError):
                        pass

        data[freq] = {
            'x': x_list,
            'y': y_list,
            'amp': amp_2d.tolist(),
            'phase': phase_2d.tolist(),
        }
    return data


class BeamFileFormatError(Exception):
    """Файл не соответствует ожидаемому формату измерения Beam№*.xlsx.

    Сообщение исключения предназначено для показа пользователю.
    """


def load_single_beam_file(file_path: str) -> dict:
    """Загрузить ОДИН файл измерения (Beam№*.xlsx) для отдельного пересчёта.

    В отличие от load_beam_pattern_results, не требует папки и scan_params.json:
    частоты берутся из самого файла, шаг сканера (dx/dy) и прочие параметры
    задаются пользователем вручную. «Луч» здесь — имя файла.

    Принять можно ЛЮБОЙ файл, но если внутри не тот формат — поднимается
    BeamFileFormatError с понятным сообщением (что именно не так).

    Returns: {
        'name': имя файла без расширения (роль «луча»),
        'freq_list': [...],
        'data': {name: {freq: {'x','y','amp','phase'}}},
        'x_list', 'y_list', 'file_path'
    }

    Raises:
        BeamFileFormatError — файл не открывается как .xlsx или не содержит
        ожидаемой структуры измерения.
    """
    if not os.path.isfile(file_path):
        raise BeamFileFormatError(f'Файл не найден:\n{file_path}')

    try:
        workbook = load_workbook(file_path)
    except Exception as e:
        logger.warning(f"Не удалось открыть как Excel: {file_path}: {e}")
        raise BeamFileFormatError(
            'Не удалось открыть файл как таблицу Excel (.xlsx).\n'
            'Имя файла может быть любым, но внутри должен быть формат '
            'измерения (как у файлов из режима «Измерение лучей АФАР»).') from e

    sheet = workbook.active
    if sheet is None:
        raise BeamFileFormatError('В книге Excel нет активного листа с данными.')

    freq_list = _detect_freqs(sheet)
    if not freq_list:
        raise BeamFileFormatError(
            'Файл не похож на измерение: не найдены строки «Frequency».\n'
            'Имя файла роли не играет — важен формат данных внутри '
            '(как в режиме «Измерение лучей АФАР»).')

    layout = _detect_layout(sheet, freq_list)
    if layout is None:
        raise BeamFileFormatError(
            'Не удалось определить структуру данных: в файле есть «Frequency», '
            'но не найден блок амплитуды/фазы ожидаемого вида.')
    len_x, len_y, size_freq_data = layout
    if len_x <= 0 or len_y <= 0:
        raise BeamFileFormatError(
            'Не удалось определить размер сетки данных (амплитуда/фаза).')

    x_list = list(range(len_x))
    y_list = list(range(len_y))
    data_by_freq = _read_sheet_data(
        sheet, freq_list, len_x, len_y, size_freq_data, x_list, y_list)

    # Должны быть хоть какие-то числовые значения амплитуды.
    has_amp = any(
        np.any(np.isfinite(np.asarray(fd['amp'], dtype=float)))
        for fd in data_by_freq.values()
    )
    if not has_amp:
        raise BeamFileFormatError(
            'Файл распознан как измерение, но не содержит числовых данных '
            'амплитуды.')

    name = os.path.splitext(os.path.basename(file_path))[0]
    logger.info(f"Загружен файл: {name}, {len(freq_list)} частот, {len_x}x{len_y} точек")
    return {
        'name': name,
        'freq_list': freq_list,
        'data': {name: data_by_freq},
        'x_list': x_list,
        'y_list': y_list,
        'file_path': file_path,
    }
