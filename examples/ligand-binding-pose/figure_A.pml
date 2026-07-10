load model.cif, complex
select ligand, resn LIG
select pocket, chain A and resi 10+11
show sticks, ligand
show cartoon, complex
color magenta, ligand
distance ligand_contact, ligand, pocket
png figure_A.png
