/* Pixel-locked, stylized Ulaanbaatar overworld. Real locations are a separate overlay. */
(()=>{
 const rect=(c,color,x,y,w,h)=>{c.fillStyle=color;c.fillRect(Math.round(x),Math.round(y),w,h)};
 function tree(c,x,y,color){rect(c,'#406452',x+3,y+8,3,5);rect(c,color,x,y+3,9,7);rect(c,color,x+2,y,5,4);rect(c,'#92e6a4',x+2,y+3,2,2)}
 function ger(c,x,y){rect(c,'#b5c8d2',x,y+4,13,8);rect(c,'#f3f5e7',x+1,y+3,11,8);rect(c,'#fff',x+3,y+1,7,3);rect(c,'#d28252',x+7,y+7,3,4)}
 function tower(c,x,y,h){rect(c,'#121a41',x-2,y-2,20,h+4);rect(c,'#384c86',x,y,16,h);for(let v=y+4;v<y+h-3;v+=6)for(let u=x+3;u<x+15;u+=5)rect(c,'#83cce0',u,v,2,2)}
 function draw(c,s){c.imageSmoothingEnabled=false;let tier=s.irl<5?0:s.irl<15?1:2,t=matchMedia('(prefers-reduced-motion: reduce)').matches?0:s.time;rect(c,['#202851','#24677c','#319db1'][tier],0,0,320,270);
 // Northern neighbourhoods and planted hillside.
 rect(c,['#29345d','#326b66','#3d8d6d'][tier],0,0,320,53);for(let i=0;i<16;i++){let x=(i*37)%320,y=4+(i*11)%28;if(i%3===0)ger(c,x,y);else tree(c,x,y,tier?'#3c9e71':'#517877')}
 // City blocks and avenues, drawn on a stable pixel grid.
 rect(c,'#262b5c',0,52,320,146);for(let y=58;y<190;y+=28)for(let x=6;x<320;x+=40){rect(c,'#374270',x,y,33,21);rect(c,'#1b244d',x+2,y+2,29,17);rect(c,'#43588a',x+4,y+4,25,2)}
 rect(c,'#798ba3',0,126,320,12);rect(c,'#d0d6d8',0,131,320,1);for(let x=0;x<320;x+=22)rect(c,'#e9edcc',x,132,8,1);rect(c,'#73849a',151,52,12,145);rect(c,'#d1d8df',156,52,1,145);
 // Skyline, square and the sail tower.
 tower(c,69,81,38);tower(c,112,71,45);tower(c,212,81,34);rect(c,'#c1c5ca',166,91,36,29);for(let y=94;y<120;y+=5)for(let x=168;x<200;x+=5)rect(c,'#e9e1ce',x,y,3,3);rect(c,'#e9d9b4',169,82,31,8);for(let x=172;x<199;x+=5)rect(c,'#7c8290',x,84,2,5);rect(c,'#34405f',182,102,3,9);
 rect(c,'#11234f',90,67,14,49);rect(c,'#238ab8',93,74,9,39);rect(c,'#00d9f4',96,68,4,38);rect(c,'#bbf8ff',98,77,2,21);
 // National park and Ferris wheel.
 rect(c,tier?'#2f8b5d':'#456967',230,65,85,54);for(let i=0;i<8;i++){let x=234+(i*23)%71,y=69+(i*13)%38;tree(c,x,y,tier===2&&i%3===0?'#f0a4ba':tier?'#3dbc70':'#628b80')};rect(c,'#d8f0ef',279,67,2,28);rect(c,'#d8f0ef',266,80,28,2);rect(c,'#d8f0ef',270,71,19,2);rect(c,'#d8f0ef',270,90,19,2);rect(c,'#d8f0ef',266,74,2,13);rect(c,'#d8f0ef',292,74,2,13);
 // Tuul River, bridges and forested southern ridge.
 rect(c,tier===0?'#2584ab':tier===1?'#29b6f6':'#00d5e8',0,201,320,29);rect(c,'#a8e9ec',0,203,320,2);for(let i=0;i<20;i++)rect(c,'#d3fdff',(i*31+Math.floor(t/200))%320,210+(i%3)*5,5,1);for(const x of [73,154,244]){rect(c,'#ddd4bb',x,197,8,39);rect(c,'#6e7886',x+2,199,4,35)}rect(c,'#185a4d',0,233,320,37);for(let i=0;i<28;i++)tree(c,(i*23)%320,237+(i*11)%18,tier?'#278a58':'#3f7166');rect(c,'#e5d8b8',170,236,14,4);rect(c,'#f5e8d1',175,228,5,9);
 if(tier>0){let x=(Math.floor(t/70)%360)-20;rect(c,'#ffd477',x,127,10,4);rect(c,'#ff7ba5',(x+110)%320,135,8,3)}if(tier===2){for(let i=0;i<5;i++){let x=175+(i*17+Math.floor(t/300))%38;rect(c,'#ffe3bf',x,115,2,2);rect(c,'#fa77a5',x,117,2,3)}}
 // Existing game coordinates and collectible logic remain intact.
 for(const p of s.pickups){rect(c,'#052b56',p.x,p.y+57,5,8);rect(c,'#a4f9ff',p.x+1,p.y+58,3,5)}let x=s.worldPos.x,y=s.worldPos.y+62;rect(c,'#101c3b',x-4,y-9,9,14);rect(c,'#b86bff',x-3,y-8,7,7);rect(c,'#00f0ff',x-2,y-6,5,2);rect(c,'#8cff00',x-2,y,5,4);
 }
 window.XotWorldDiorama={draw};
})();
