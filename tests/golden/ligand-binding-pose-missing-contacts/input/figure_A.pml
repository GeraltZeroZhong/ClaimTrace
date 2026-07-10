load model.cif, complex
select active_site, chain A and resi 10
select ligand, resn LIG
show sticks, ligand
distance d1, ligand, active_site
png figure_A.png
