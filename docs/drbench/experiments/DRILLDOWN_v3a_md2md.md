## 1. Distribuição por componente (dev-986 md2md, w1)
| run | comp | n | mean | median | %<50 |
|---|---|---|---|---|---|
| v3a-clean | text | 949 | 77.7 | 88.7 | 14% |
| v3a-clean | reading_order | 925 | 60.3 | 62.5 | 29% |
| v3a-clean | teds | 68 | 62.4 | 71.0 | 28% |
| v3a-clean | overall_no_cdm | 950 | 69.2 | 74.3 | 17% |
| differ-v2 | text | 950 | 78.4 | 90.4 | 14% |
| differ-v2 | reading_order | 925 | 58.3 | 60.0 | 37% |
| differ-v2 | teds | 68 | 62.4 | 71.0 | 28% |
| differ-v2 | overall_no_cdm | 950 | 68.5 | 71.0 | 18% |
| mineru | text | 949 | 72.4 | 91.5 | 24% |
| mineru | reading_order | 925 | 52.7 | 57.1 | 36% |
| mineru | teds | 68 | 62.3 | 71.0 | 28% |
| mineru | overall_no_cdm | 950 | 62.7 | 73.3 | 25% |
| docling | text | 950 | 76.0 | 89.6 | 17% |
| docling | reading_order | 925 | 53.8 | 50.0 | 45% |
| docling | teds | 53 | 39.1 | 26.7 | 66% |
| docling | overall_no_cdm | 950 | 64.5 | 66.5 | 21% |

## 2. Piores páginas v3a-clean

### text (bottom 20)
| uuid | page | subject | layout | special | rotate | text | RO | mineru text | docling text | GT cats |
|---|---|---|---|---|---|---|---|---|---|---|
| 11fb213b | 71 | SELF-HELP | single_column | ['table_horizontal', 'table_fewer_line'] | ['rotate270'] | 0.0 | 0.0 | 0.0 | 0.0 | {'footer': 1, 'page_number': 1, 'table': 1, 'table_caption': 1} |
| 11fb213b | 72 | SELF-HELP | single_column | ['table_horizontal', 'table_wireless_line'] | None | 0.0 | 0.0 | 0.0 | 100.0 | {'footer': 1, 'page_number': 1, 'table': 1} |
| 11fb213b | 74 | SELF-HELP | single_column | ['table_horizontal', 'table_wireless_line'] | None | 0.0 | 0.0 | 0.0 | 100.0 | {'footer': 1, 'page_number': 1, 'table': 1} |
| 4d5947df | 114 | DESIGN | single_column | [] | None | 0.0 | – | 0.0 | 0.0 | {'figure': 2, 'text_block': 1} |
| 4d5947df | 116 | DESIGN | single_column | [] | None | 0.0 | – | 0.0 | 0.0 | {'figure': 2, 'text_block': 1} |
| 4d5947df | 118 | DESIGN | single_column | [] | None | 0.0 | – | 0.0 | 0.0 | {'figure': 2, 'text_block': 1} |
| 4d5947df | 120 | DESIGN | single_column | [] | None | 0.0 | – | 0.0 | 0.0 | {'figure': 2, 'text_block': 1} |
| 4d5947df | 122 | DESIGN | single_column | ['fuzzy_scan'] | None | 0.0 | – | 0.0 | 0.0 | {'figure': 2, 'text_block': 1} |
| 4d5947df | 124 | DESIGN | single_column | [] | None | 0.0 | – | 0.0 | 0.0 | {'figure': 2, 'text_block': 1} |
| 547e2947 | 12 | JUVENILENONFICTION | other_layout | [] | None | 0.0 | 100.0 | 0.0 | 0.0 | {'figure': 1, 'text_block': 2} |
| 591d786d | 11 | JUVENILENONFICTION | other_layout | ['table_full_line', 'table_span'] | None | 0.0 | 0.0 | 0.0 | 100.0 | {'page_number': 1, 'table': 1} |
| 591d786d | 16 | JUVENILENONFICTION | other_layout | ['table_horizontal', 'table_full_line', 'fuzzy_scan'] | None | 0.0 | 0.0 | 0.0 | 100.0 | {'page_number': 1, 'table': 1} |
| 591d786d | 19 | JUVENILENONFICTION | single_column | ['table_full_line'] | None | 0.0 | 0.0 | 0.0 | 100.0 | {'page_number': 1, 'table': 1} |
| 591d786d | 22 | JUVENILENONFICTION | single_column | ['table_full_line'] | None | 0.0 | – | 0.0 | 100.0 | {'page_number': 1, 'table': 1} |
| 591d786d | 20 | JUVENILENONFICTION | single_column | ['table_full_line'] | None | 0.0 | 100.0 | 0.0 | 0.1 | {'page_number': 1, 'table': 1} |
| 591d786d | 21 | JUVENILENONFICTION | single_column | ['table_full_line'] | None | 0.1 | 100.0 | 0.0 | 0.1 | {'page_number': 1, 'table': 1} |
| 591d786d | 18 | JUVENILENONFICTION | single_column | ['table_full_line'] | None | 0.1 | 100.0 | 0.0 | 0.1 | {'page_number': 1, 'table': 1} |
| 591d786d | 10 | JUVENILENONFICTION | other_layout | ['table_full_line'] | None | 0.1 | 100.0 | 0.0 | 0.1 | {'page_number': 1, 'table': 1} |
| 591d786d | 13 | JUVENILENONFICTION | single_column | ['table_horizontal', 'table_full_line'] | None | 0.1 | 100.0 | 0.0 | 0.2 | {'page_number': 1, 'table': 1} |
| 591d786d | 15 | JUVENILENONFICTION | single_column | ['table_horizontal', 'table_full_line'] | None | 0.1 | 100.0 | 0.0 | 0.2 | {'page_number': 1, 'table': 1} |

### reading_order (bottom 20)
| uuid | page | subject | layout | special | rotate | text | RO | mineru reading_order | docling reading_order | GT cats |
|---|---|---|---|---|---|---|---|---|---|---|
| 0fbef2f7 | 73 | COMICS&GRAPHICNOVELS | other_layout | ['colorful_backgroud'] | None | 34.3 | 0.0 | 0.0 | 0.0 | {'figure': 1, 'text_block': 10} |
| 11fb213b | 71 | SELF-HELP | single_column | ['table_horizontal', 'table_fewer_line'] | ['rotate270'] | 0.0 | 0.0 | 0.0 | 0.0 | {'footer': 1, 'page_number': 1, 'table': 1, 'table_caption': 1} |
| 11fb213b | 72 | SELF-HELP | single_column | ['table_horizontal', 'table_wireless_line'] | None | 0.0 | 0.0 | 0.0 | 100.0 | {'footer': 1, 'page_number': 1, 'table': 1} |
| 11fb213b | 74 | SELF-HELP | single_column | ['table_horizontal', 'table_wireless_line'] | None | 0.0 | 0.0 | 0.0 | 100.0 | {'footer': 1, 'page_number': 1, 'table': 1} |
| 11fb213b | 79 | SELF-HELP | single_column | ['table_wireless_line'] | None | 74.4 | 0.0 | 0.0 | 100.0 | {'header': 1, 'page_number': 1, 'table': 1, 'table_caption': 1} |
| 15efdcba | 190 | FICTION | single_column | [] | None | 97.8 | 0.0 | 0.0 | 0.0 | {'header': 1, 'title': 2} |
| 2ddd9037 | 4 | GAMES&ACTIVITIES | single_column | [] | None | 72.0 | 0.0 | 50.0 | 100.0 | {'figure': 1, 'footer': 1, 'text_block': 2} |
| 2ddd9037 | 14 | GAMES&ACTIVITIES | single_column | [] | None | 66.7 | 0.0 | 50.0 | 100.0 | {'figure': 1, 'footer': 1, 'text_block': 2} |
| 38a7285c | 218 | ART | single_column | [] | None | 97.3 | 0.0 | 25.0 | 0.0 | {'figure': 1, 'figure_caption': 1, 'header': 1, 'page_number': 1, 'text_block': 2} |
| 3c0aee4c | 23 | HUMOR | other_layout | [] | None | 55.1 | 0.0 | 50.0 | 0.0 | {'figure': 1, 'figure_caption': 1, 'text_block': 2} |
| 3c0aee4c | 24 | HUMOR | other_layout | [] | None | 72.5 | 0.0 | 0.0 | 100.0 | {'figure': 1, 'figure_caption': 1, 'text_block': 2} |
| 3c0aee4c | 25 | HUMOR | other_layout | [] | ['rotate270', 'rotate90'] | 50.1 | 0.0 | 33.3 | 66.7 | {'figure': 1, 'figure_caption': 1, 'text_block': 6} |
| 4d264540 | 9 | POLITICALSCIENCE | single_column | [] | None | 43.2 | 0.0 | 0.0 | 100.0 | {'figure': 1, 'footer': 1, 'text_block': 1} |
| 4df2a4de | 60 | SOCIALSCIENCE | single_column | ['table_wireless_line', 'colorful_backgroud'] | None | 96.2 | 0.0 | 0.0 | 100.0 | {'header': 1, 'page_number': 1, 'table': 1, 'table_caption': 1} |
| 591d786d | 8 | JUVENILENONFICTION | single_column | ['table_full_line'] | ['rotate270'] | 68.8 | 0.0 | 0.0 | 100.0 | {'page_number': 1, 'table': 2, 'table_caption': 1} |
| 591d786d | 11 | JUVENILENONFICTION | other_layout | ['table_full_line', 'table_span'] | None | 0.0 | 0.0 | 0.0 | 100.0 | {'page_number': 1, 'table': 1} |
| 591d786d | 16 | JUVENILENONFICTION | other_layout | ['table_horizontal', 'table_full_line', 'fuzzy_scan'] | None | 0.0 | 0.0 | 0.0 | 100.0 | {'page_number': 1, 'table': 1} |
| 591d786d | 19 | JUVENILENONFICTION | single_column | ['table_full_line'] | None | 0.0 | 0.0 | 0.0 | 100.0 | {'page_number': 1, 'table': 1} |
| 67587089 | 93 | STUDYAIDS | single_column | ['fuzzy_scan'] | None | 7.0 | 0.0 | 0.0 | 100.0 | {'footer': 2, 'header': 1, 'page_number': 1, 'text_mask': 1} |
| 67587089 | 95 | STUDYAIDS | single_column | ['fuzzy_scan'] | None | 7.0 | 0.0 | 0.0 | 100.0 | {'footer': 2, 'header': 1, 'page_number': 1, 'text_mask': 1} |

## 3. Por subject (v3a-clean), ordenado por overall_no_cdm
| subject | n | overall | text | RO | TEDS(n) | mineru ov | docling ov |
|---|---|---|---|---|---|---|---|
| PSYCHOLOGY | 15 | 31.5 | 60.2 | 2.9 | None(0) | 15.5 | 36.6 |
| COMICS&GRAPHICNOVELS | 14 | 34.8 | 30.8 | 38.7 | None(0) | 0.7 | 35.0 |
| GAMES&ACTIVITIES | 45 | 53.1 | 57.8 | 48.4 | None(0) | 47.1 | 51.1 |
| SPORTS&RECREATION | 45 | 54.0 | 62.2 | 45.5 | 50.0(1) | 48.5 | 51.0 |
| POETRY | 30 | 54.9 | 68.9 | 40.8 | None(0) | 57.1 | 37.5 |
| TECHNOLOGY&ENGINEERING | 15 | 58.5 | 73.6 | 43.4 | None(0) | 62.8 | 52.1 |
| SELF-HELP | 15 | 58.8 | 54.7 | 48.1 | 59.4(14) | 40.5 | 52.1 |
| JUVENILENONFICTION | 41 | 62.4 | 48.5 | 73.6 | 50.6(13) | 19.3 | 69.1 |
| COOKING | 11 | 63.0 | 61.4 | 62.6 | 85.4(1) | 62.3 | 47.6 |
| STUDYAIDS | 29 | 63.4 | 73.6 | 54.6 | 35.1(6) | 57.4 | 69.2 |
| LANGUAGEARTS&DISCIPLINES | 15 | 64.2 | 82.6 | 43.4 | 88.3(2) | 67.7 | 68.2 |
| BIOGRAPHY&AUTOBIOGRAPHY | 15 | 64.8 | 81.1 | 48.6 | None(0) | 78.5 | 57.8 |
| YOUNGADULTNONFICTION | 15 | 65.9 | 80.2 | 51.5 | None(0) | 62.7 | 58.0 |
| DESIGN | 42 | 66.3 | 77.8 | 62.9 | None(0) | 59.7 | 70.0 |
| TRANSPORTATION | 30 | 66.6 | 64.0 | 64.7 | 68.3(15) | 63.8 | 58.6 |
| BODY,MIND&SPIRIT | 15 | 67.8 | 88.8 | 46.9 | None(0) | 74.4 | 56.3 |
| HUMOR | 15 | 68.0 | 64.9 | 71.1 | None(0) | 71.0 | 68.8 |
| POLITICALSCIENCE | 25 | 69.0 | 80.3 | 49.8 | 89.6(4) | 61.4 | 69.1 |
| TRUECRIME | 14 | 70.7 | 89.1 | 52.3 | None(0) | 80.1 | 53.8 |
| LAW | 15 | 71.3 | 78.4 | 64.2 | None(0) | 67.9 | 71.6 |
| ART | 15 | 71.5 | 95.0 | 47.9 | None(0) | 73.8 | 56.1 |
| FICTION | 14 | 73.8 | 82.1 | 65.5 | None(0) | 86.8 | 65.2 |
| PERFORMINGARTS | 15 | 74.1 | 85.4 | 60.3 | None(0) | 74.8 | 70.5 |
| ARCHITECTURE | 14 | 74.5 | 98.1 | 51.0 | None(0) | 72.8 | 79.7 |
| SOCIALSCIENCE | 45 | 74.6 | 84.1 | 65.8 | 36.6(2) | 74.3 | 66.1 |
| MEDICAL | 15 | 75.4 | 89.0 | 61.9 | None(0) | 79.4 | 63.7 |
| CRAFTS&HOBBIES | 29 | 75.9 | 64.0 | 87.8 | None(0) | 57.1 | 69.5 |
| GARDENING | 29 | 76.7 | 89.0 | 64.1 | 82.5(2) | 66.6 | 65.1 |
| LITERARYCRITICISM | 15 | 77.3 | 88.3 | 66.3 | None(0) | 77.6 | 64.9 |
| YOUNGADULTFICTION | 42 | 77.6 | 80.1 | 73.5 | None(0) | 55.3 | 80.3 |
| HISTORY | 15 | 77.6 | 92.8 | 62.6 | 89.4(1) | 81.6 | 71.2 |
| HOUSE&HOME | 52 | 77.9 | 81.3 | 73.3 | 88.6(1) | 69.3 | 76.2 |
| COMPUTERS | 30 | 78.1 | 92.1 | 64.9 | 70.2(2) | 67.0 | 69.6 |
| EDUCATION | 73 | 78.8 | 91.8 | 65.5 | 65.6(3) | 72.9 | 62.4 |
| FAMILY&RELATIONSHIPS | 15 | 79.2 | 94.8 | 63.6 | None(0) | 78.9 | 62.3 |
| BUSINESS&ECONOMICS | 30 | 82.3 | 97.1 | 67.4 | 91.3(1) | 84.8 | 93.0 |
| PHILOSOPHY | 30 | 82.4 | 93.1 | 71.6 | None(0) | 78.3 | 75.0 |
| PETS | 11 | 86.7 | 90.1 | 83.3 | None(0) | 79.9 | 86.7 |

## 3b. Por layout / special_issue (v3a-clean)

### layout
| value | n | overall | text | RO |
|---|---|---|---|---|
| three_column | 42 | 61.8 | 67.8 | 55.5 |
| other_layout | 174 | 64.7 | 64.3 | 63.6 |
| 1andmore_column | 95 | 67.7 | 80.3 | 55.3 |
| single_column | 493 | 70.2 | 80.9 | 58.9 |
| double_column | 146 | 74.5 | 83.7 | 65.3 |

### special_issue
| value | n | overall | text | RO |
|---|---|---|---|---|
| table_horizontal,table_full_line,fuzzy_scan | 1 | 0.8 | 0.0 | 0.0 |
| table_with_formula,table_full_line | 1 | 30.9 | 72.3 | 13.3 |
| colorful_backgroud,fuzzy_scan,table_wireless_line | 1 | 34.5 | 52.4 | 16.7 |
| table_full_line,table_span | 2 | 39.6 | 33.2 | 38.9 |
| table_wireless_line | 8 | 41.3 | 54.9 | 32.5 |
| table_horizontal,table_wireless_line | 4 | 43.6 | 8.6 | 33.3 |
| table_full_line,fuzzy_scan | 2 | 47.2 | 40.6 | 68.8 |
| table_full_line | 23 | 48.8 | 27.6 | 63.1 |
| fuzzy_scan,table_full_line | 1 | 48.9 | 64.5 | 33.3 |
| table_wireless_line,colorful_backgroud | 1 | 51.2 | 96.2 | 0.0 |
| table_full_line,table_with_formula | 1 | 58.1 | 79.6 | 42.1 |
| colorful_backgroud,table_full_line | 6 | 59.1 | 48.0 | 67.4 |
| table_fewer_line,table_horizontal | 1 | 62.5 | 66.9 | 35.3 |
| colorful_backgroud,fuzzy_scan | 27 | 62.9 | 64.7 | 59.7 |
| table_horizontal,table_full_line | 2 | 64.1 | 0.1 | 100.0 |
| fuzzy_scan | 99 | 64.9 | 75.4 | 54.9 |
| table_horizontal,table_fewer_line | 10 | 68.0 | 66.0 | 56.7 |
| colorful_backgroud,table_fewer_line,table_full_line | 1 | 68.5 | 83.4 | 60.0 |
| fuzzy_scan,colorful_backgroud | 5 | 70.0 | 50.0 | 90.0 |
| table_fewer_line | 13 | 70.1 | 86.7 | 51.0 |
|  | 637 | 71.6 | 82.9 | 60.5 |
| colorful_backgroud | 103 | 71.7 | 72.9 | 68.5 |
| table_wireless_line,fuzzy_scan | 1 | 91.6 | 99.7 | 85.7 |

### language
| value | n | overall | text | RO |
|---|---|---|---|---|
| english,other | 2 | 34.0 | 41.6 | 52.9 |
| english,french | 7 | 61.3 | 80.9 | 33.7 |
| other | 1 | 68.5 | 87.1 | 50.0 |
| english | 940 | 69.4 | 77.7 | 60.5 |

### rotate
| value | n | overall | text | RO |
|---|---|---|---|---|
| horizontal | 1 | 28.8 | 54.2 | 25.0 |
| rotate270,rotate90 | 2 | 29.4 | 51.6 | 7.1 |
| rotate270 | 82 | 61.5 | 75.4 | 43.8 |
| other | 12 | 66.4 | 66.3 | 64.2 |
| None | 841 | 70.2 | 78.2 | 61.9 |
| rotate90 | 12 | 70.3 | 77.8 | 60.4 |

## 4. Tabelas (TEDS) — piores 10 em v3a-clean vs mineru/docling
| uuid | page | subject | v3a | mineru | docling |
|---|---|---|---|---|---|
| 591d786d | 8 | JUVENILENONFICTION | 1.0 | 1.0 | 0.7 |
| 591d786d | 9 | JUVENILENONFICTION | 2.1 | 2.1 | – |
| 591d786d | 16 | JUVENILENONFICTION | 2.3 | 2.3 | 2.0 |
| 11fb213b | 79 | SELF-HELP | 3.4 | 3.4 | 97.5 |
| 591d786d | 17 | JUVENILENONFICTION | 5.0 | 5.0 | – |
| 591d786d | 18 | JUVENILENONFICTION | 6.1 | 6.1 | – |
| 67587089 | 85 | STUDYAIDS | 7.1 | 7.1 | 6.7 |
| 67587089 | 86 | STUDYAIDS | 7.1 | 7.1 | 5.7 |
| 11fb213b | 81 | SELF-HELP | 9.3 | 9.3 | 18.1 |
| 4df2a4de | 58 | SOCIALSCIENCE | 15.8 | 15.8 | 16.4 |

páginas com TEDS (GT tem tabela): mineru 68, docling 53, v3a 68

## 6. Oracle por página (max entre v3a, mineru, docling) — md2md dev-986
v3a evalai_style = 68.20
oracle por página = 74.48 (wins: {'docling': 215, 'mineru': 322, 'v3a': 413})
oracle por componente = 75.62
  oracle text: 83.6 (v3a 77.7)
  oracle reading_order: 70.0 (v3a 60.3)
  oracle teds: 64.8 (v3a 62.4)
