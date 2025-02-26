# -*- coding: utf-8 -*-

import sys
from pathlib import Path, WindowsPath
import re
import numpy as np
import json
from autoeq.frequency_response import FrequencyResponse
from autoeq.utils import is_file_name_allowed
ROOT_PATH = Path(__file__).parent.parent
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(1, str(ROOT_PATH))
from dbtools.name_index import NameIndex, NameItem
from dbtools.crawler import Crawler
from dbtools.constants import MEASUREMENTS_PATH

CRINACLE_PATH = MEASUREMENTS_PATH.joinpath('crinacle')


class UnknownRigError(Exception):
    pass


class CrinacleCrawler(Crawler):
    raw_data_rig_map = {
        '4620 IEM Measurements': 'Bruel & Kjaer 4620',
        'EARS + 711 (TSV txt) (Legacy)': 'EARS + 711',
        'GRAS 43AG-7': 'GRAS 43AG-7',
        'IEC60318-4 IEM Measurements (TSV txt)': '711',
    }

    raw_data_form_map = {
        '4620 IEM Measurements': 'in-ear',
        'EARS + 711 (TSV txt) (Legacy)': 'over-ear',
        'GRAS 43AG-7': 'over-ear',
        'IEC60318-4 IEM Measurements (TSV txt)': 'in-ear',
    }

    def __init__(self, driver=None, delete_existing_on_prompt=True, redownload=False):
        super().__init__(driver=driver, delete_existing_on_prompt=delete_existing_on_prompt, redownload=redownload)
        self.book_index = self.parse_books()

    def parse_books(self):
        """Downloads parses phone books to get names

        Returns:
            NameIndex
        """
        # 4620 measurements name index
        raw = self.download(
            'https://crinacle.com/graphing/data_4620/phone_book.json', CRINACLE_PATH.joinpath('phone_book_4620.json'))
        bk4620_map = self.parse_book(json.loads(raw.decode('utf-8')))
        # Ears-711 measurements name index
        raw = self.download(
            'https://crinacle.com/graphing/data_hp/phone_book.json', CRINACLE_PATH.joinpath('phone_book_hp.json'))
        ears_711_map = self.parse_book(json.loads(raw.decode('utf-8')))
        # Gras measurements name index
        raw = self.download(
            'https://crinacle.com/graphing/data_hp_gras/phone_book.json',
            CRINACLE_PATH.joinpath('phone_book_hp_gras.json'))
        gras_map = self.parse_book(json.loads(raw.decode('utf-8')))
        # 711 IEM measurements name index
        raw = self.download(
            'https://crinacle.com/graphing/data/phone_book.json',
            CRINACLE_PATH.joinpath('phone_book.json'))
        iem_711_map = self.parse_book(json.loads(raw.decode('utf-8')))
        return {
            '4620 IEM Measurements': bk4620_map,
            'EARS + 711 (TSV txt) (Legacy)': ears_711_map,
            'GRAS 43AG-7': gras_map,
            'IEC60318-4 IEM Measurements (TSV txt)': iem_711_map,
        }

    def parse_book(self, data):
        """Parses a phone book as dict with false names as keys and true names as values.

        Args:
            data: Phone book object

        Returns:
            Dict with phone book file names as keys and and phone book names as values
        """
        book = dict()
        for manufacturer in data:
            # Manufacturer name in the phone books is made up of "name" and potentially "suffix"
            # e.g. name="Final", suffix="Audio Design" --> "Final Audio Design"
            manufacturer_name = manufacturer['name']
            if 'suffix' in manufacturer:
                manufacturer_name += f' {manufacturer["suffix"]}'
            for model in manufacturer['phones']:
                if type(model) == str:
                    # Sometimes the model is nothing but a single string
                    book[model.strip()] = f'{manufacturer_name} {model}'.strip()
                else:
                    # Sometimes the model is an object with "name", "collab", list of "file"s and list of "suffix"es
                    # Collab(oration) field is ignored, naming needs to be checked manually against other dbs anyways
                    if type(model['file']) == str:  # Wrap a single file string in list to iterate with others
                        model['file'] = [model['file']]
                    if 'suffix' in model:
                        # Suffixes indicate modes (passive, active, ANC, ...) and other such things
                        # When suffix field is present, the suffixes and files are lists with matching indexes for
                        # the items
                        for file_name, suffix in zip(model['file'], model['suffix']):
                            book[file_name.strip()] = f'{manufacturer_name} {model["name"]} {suffix}'
                    else:
                        for file_name in model['file']:
                            book[file_name.strip()] = f'{manufacturer_name} {model["name"]}'
        return book

    def read_name_index(self):
        self.name_index = NameIndex.read_tsv(CRINACLE_PATH.joinpath('name_index.tsv'))
        return self.name_index

    def write_name_index(self):
        self.name_index.write_tsv(CRINACLE_PATH.joinpath('name_index.tsv'))

    @staticmethod
    def get_url_from_file_path(raw_data_file_path):
        """Creates URL from file path"""
        url = raw_data_file_path.relative_to(ROOT_PATH)
        return 'file://' + str(url).replace('\\', '/') if type(url) == WindowsPath else str(url)

    def get_item_from_file_path(self, raw_data_file_path):
        """Creates NameItem from path to a TXT file in raw_data"""
        url = self.get_url_from_file_path(raw_data_file_path)
        index_item = self.name_index.find_one(url=url)
        if index_item is not None:  # Existing item in the name index, ground truth
            item = NameItem(
                source_name=index_item.source_name, name=index_item.name, form=index_item.form, url=url)
        else:
            item = NameItem(
                url=url,
                form=self.raw_data_form_map[raw_data_file_path.parent.name],
                rig=self.raw_data_rig_map[raw_data_file_path.parent.name])
        return item

    def crawl(self):
        self.name_index = self.read_name_index()
        self.crawl_index = NameIndex()
        for dir_path in CRINACLE_PATH.joinpath('raw_data').glob('*'):
            for item in [self.get_item_from_file_path(fp) for fp in dir_path.glob('*.txt')]:
                self.crawl_index.add(item)
        return self.crawl_index

    @staticmethod
    def get_file_path_from_url(url):
        return ROOT_PATH.joinpath(re.sub(r'^file://', '', url))

    @staticmethod
    def normalize_file_name(file_name):
        file_name = re.sub(r' #\d+ [LR]\.txt$', '', file_name)
        file_name = re.sub(r' [LR](?:\d+)?\.txt$', '', file_name)
        file_name = re.sub(r'\.txt$', '', file_name)
        return file_name

    def source_group_key(self, item):
        return self.normalize_file_name(re.sub(r'^file://', '', item.url))

    def resolve(self, item):
        """Resolve name for a single item. Updates the item in place.

        Args:
            item: The crawl index NameItem to resolve

        Returns:
            True if resolution was successful, False if user needs to be prompted
        """
        group_key = self.source_group_key(item)
        for true_item in self.name_index.items:
            if group_key == self.source_group_key(true_item):
                if true_item.name is not None:
                    item.name = true_item.name
                if true_item.source_name is not None:
                    item.source_name = true_item.source_name
                if true_item.form is not None:
                    item.form = true_item.form
                if true_item.rig is not None:
                    item.rig = true_item.rig
                return item
        return None

    def guess_name(self, item):
        """Gets intermediate name with false name."""
        name = item.source_name
        if name is None:
            file_path = self.get_file_path_from_url(item.url)
            item_from_url = self.get_item_from_file_path(file_path)
            name = item_from_url.source_name
        if name is None:
            normalized_file_name = self.normalize_file_name(file_path.name)
            if normalized_file_name in self.book_index[file_path.parent.name]:
                name = self.book_index[file_path.parent.name][normalized_file_name]
            else:
                return normalized_file_name
        name = name.replace('(w/ ', '(')
        name = re.sub(r' pads\)', ' earpads)', name, flags=re.IGNORECASE)
        match = re.search(r' S\d+[$ ](?:\.txt)?$', name)
        if match:
            name = re.sub(r' S(\d+)[$ ]', r' (sample \1) ', name)
            name = re.sub(r'\s{2,}', ' ', name)
        return name

    def target_group_key(self, item):
        return f'{item.form}/{item.rig}/{item.name}'

    def target_path(self, item):
        if item.is_ignored or item.form is None or item.rig is None or item.name is None:
            return None
        path = CRINACLE_PATH.joinpath('data', item.form, item.rig, f'{item.name}.csv')
        if not is_file_name_allowed(item.name):
            raise ValueError(f'Target path cannot be "{path}"')
        return path

    def process_group(self, items, new_only=True):
        if items[0].is_ignored:
            return
        file_path = self.target_path(items[0])
        if new_only and file_path.exists():
            return
        avg_fr = FrequencyResponse(name=items[0].name)
        avg_fr.raw = np.zeros(avg_fr.frequency.shape)
        for item in items:
            fr = FrequencyResponse.read_csv(self.get_file_path_from_url(item.url))
            fr.interpolate()
            fr.center()
            avg_fr.raw += fr.raw
        avg_fr.raw /= len(items)
        Path(file_path.parent).mkdir(exist_ok=True, parents=True)
        avg_fr.write_csv(file_path)

    def list_existing_files(self):
        return list(CRINACLE_PATH.joinpath('data').glob('**/*.csv'))
