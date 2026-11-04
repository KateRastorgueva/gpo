# Архив

`tusur_docs_host_broken_2026-11-05.zip` (Git LFS, 134 МБ): папка `tusur docs` с
командного хоста в том виде, в каком она была 05.11.2026. Для скачивания нужен
`git lfs install`.

В архиве лежат правильные оригиналы, новые документы и 20 испорченных копий с
суффиксом « (1)» (пробел перед скобкой); 18 PDF из них были загружены в AnythingLLM. В каждой такой копии лежит предыдущий по
алфавиту файл, что подтверждено SHA-256 по `scripts/tusur_docs_manifest.json`:

| Копия « (1)» | Что внутри на самом деле |
|---|---|
| Izmeneniya_ustav (1).pdf | FAQбезкатегорий546.xlsx |
| FAQбезкатегорий546 (1).xlsx | 2026-27-.pdf |
| Izmeneniya_v_ustav_02_08_19 (1).pdf | Izmeneniya_ustav.pdf |
| Izmeneniya_v_ustav_TUSURa_16.03.2020 (1).pdf | Izmeneniya_v_ustav_02_08_19.pdf |
| Kollektivnyi_dogovor_2024 (1).pdf | Izmeneniya_v_ustav_TUSURa_16.03.2020.pdf |
| Otchet_2023 (1).pdf | Kollektivnyi_dogovor_2024.pdf |
| Otchet_…_2024_god (1).pdf | Otchet_2023.pdf |
| Otchet_…_2024_god_Xarakteristika_OPOP (1).pdf | Otchet_…_2024_god.pdf |
| Otchet_…_2025_god (1).pdf | Otchet_…_2024_god_Xarakteristika_OPOP.pdf |
| Otchet_…_2025_god_(xarakteristiki_OPOP) (1).pdf | Otchet_…_2025_god.pdf |
| Pologhenie_ob_otdele_normativnogo_obespecheniya (1).pdf | Otchet_…_2025_god_(xarakteristiki_OPOP).pdf |
| Pologhenie_o_vnutrennei_sisteme_ocenki_kachestva_obrazovaniya (1).pdf | Pologhenie_ob_otdele_normativnogo_obespecheniya.pdf |
| Polozheniye_po_provedeniyu_tekushchego_kontrolya_uspevayemosti_i (1).pdf | Pologhenie_o_vnutrennei_sisteme_ocenki_kachestva_obrazovaniya.pdf |
| Poryadok_oformleniya_… (1).pdf | Polozheniye_po_provedeniyu_tekushchego_kontrolya_uspevayemosti_i.pdf |
| Poryadok_perevoda_… (1).pdf | Poryadok_oformleniya_….pdf |
| Pravila_priema_2026 (1).pdf | Poryadok_perevoda_….pdf |
| Pravila_rasporyadka_02.11.2017_(1) (1).pdf | Pravila_priema_2026.pdf |
| Reghim_zanyatiy_…_16.05.2019(1) (1).pdf | Pravila_rasporyadka_02.11.2017_(1).pdf |
| Ustav_2018 (1).pdf | Reghim_zanyatiy_…_16.05.2019(1).pdf |
| Ustav_FGAOU_TUSUR_24(1) (1).pdf | Ustav_2018.pdf |

Именно эти копии были загружены в AnythingLLM, поэтому ответы называли не тот
документ. Файлы с «(1)» без пробела (например `739(1).pdf`) к сдвигу не относятся.
