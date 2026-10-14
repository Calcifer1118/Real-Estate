const BASE = location.href.replace(/[#?].*$/,"").replace(/[^/]*$/,"");
function style3d(){
  return { version:8,
    sources:{ dem:{ type:"raster-dem", tiles:[BASE+"tiles/dem/{z}/{x}/{y}.png"], encoding:"terrarium", tileSize:256, minzoom:8, maxzoom:12, bounds:[120.55,13.95,121.15,14.70] } },
    terrain:{ source:"dem", exaggeration:1.6 },
    sky:{ "sky-color":"#0b0e0f", "horizon-color":"#20282b", "fog-color":"#0b0e0f", "fog-ground-blend":0.55, "horizon-fog-blend":0.7, "sky-horizon-blend":0.6, "atmosphere-blend":0 },
    layers:[
      { id:"bg", type:"background", paint:{ "background-color":"#121816" } },
      { id:"hill", type:"hillshade", source:"dem", paint:{ "hillshade-shadow-color":"#030505", "hillshade-highlight-color":"#7d8c80", "hillshade-accent-color":"#1c2621", "hillshade-exaggeration":0.8 } }
    ] };
}
// Water and highways from the same hand-traced data as the flat map.
function addVectors(map,P){
  const water=[], roads=[];
  P.maps.forEach(g=>{ (g.water||[]).forEach(w=>water.push({ type:"Feature", properties:{}, geometry:{ type:"Polygon", coordinates:[[...w.pts, w.pts[0]]] } }));
    (g.roads||[]).forEach(r=>roads.push({ type:"Feature", properties:{}, geometry:{ type:"LineString", coordinates:r.pts } })); });
  map.addSource("water",{ type:"geojson", data:{ type:"FeatureCollection", features:water } });
  map.addLayer({ id:"water", type:"fill", source:"water", paint:{ "fill-color":"#1b2f36", "fill-opacity":0.85 } });
  map.addSource("roads",{ type:"geojson", data:{ type:"FeatureCollection", features:roads } });
  map.addLayer({ id:"roads", type:"line", source:"roads", layout:{ "line-cap":"round", "line-join":"round" }, paint:{ "line-color":"#9aa49f", "line-width":["interpolate",["linear"],["zoom"],8,1.2,14,5], "line-opacity":0.75 } });
}
