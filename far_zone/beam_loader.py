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
            data[beam_num] = {}
            
            workbook = load_workbook(file_path)
            sheet = workbook.active
            
            for freq_idx, freq in enumerate(freq_list):
                row_start = freq_idx * size_freq_data + 1
                
                # Инициализируем массивы
                amp_2d = np.full((len_y, len_x), np.nan)
                phase_2d = np.full((len_y, len_x), np.nan)
                
                # Загружаем амплитуду
                for x_idx in range(len_x):
                    for y_idx in range(len_y):
                        cell = sheet.cell(row_start + 2 + x_idx, y_idx + 1)
                        if cell.value is not None:
                            try:
                                amp_2d[y_idx, x_idx] = float(cell.value)
                            except (ValueError, TypeError):
                                pass
                
                # Загружаем фазу
                for x_idx in range(len_x):
                    for y_idx in range(len_y):
                        cell = sheet.cell(row_start + 3 + len_x + x_idx, y_idx + 1)
                        if cell.value is not None:
                            try:
                                phase_2d[y_idx, x_idx] = float(cell.value)
                            except (ValueError, TypeError):
                                pass
                
                data[beam_num][freq] = {
                    'x': x_list,
                    'y': y_list,
                    'amp': amp_2d.tolist(),
                    'phase': phase_2d.tolist()
                }
        
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
