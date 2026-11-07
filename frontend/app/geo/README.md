# Confini per la mappa del Territorio

- `regioni.geojson`, `province.geojson`: confini amministrativi semplificati (mapshaper, 4% e 6%).
- `regioni-centri.geojson`, `province-centri.geojson`: punti interni per i volti e le sigle.

Fonte: ISTAT, tramite [openpolis/geojson-italy](https://github.com/openpolis/geojson-italy).
Licenza: [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/) — l'attribuzione a ISTAT
compare sotto la mappa e va mantenuta.

Per rigenerarli:

```sh
npx mapshaper limits_IT_regions.geojson -simplify 4% keep-shapes \
  -filter-fields reg_name,reg_istat_code -rename-fields name=reg_name,istat=reg_istat_code \
  -o regioni.geojson precision=0.0001
npx mapshaper limits_IT_provinces.geojson -simplify 6% keep-shapes \
  -filter-fields prov_name,prov_acr,reg_istat_code,reg_name \
  -rename-fields name=prov_name,sigla=prov_acr,region_istat=reg_istat_code,region_name=reg_name \
  -o province.geojson precision=0.0001
npx mapshaper limits_IT_regions.geojson -points inner -filter-fields reg_name,reg_istat_code \
  -rename-fields name=reg_name,istat=reg_istat_code -o regioni-centri.geojson precision=0.0001
npx mapshaper limits_IT_provinces.geojson -points inner -filter-fields prov_name,prov_acr,reg_istat_code \
  -rename-fields name=prov_name,sigla=prov_acr,region_istat=reg_istat_code -o province-centri.geojson precision=0.0001
```

MapLibre GL JS (`../vendor/maplibre/`, licenza BSD-3, vedi `LICENSE.txt`) è la build CSP 5.24.0.
