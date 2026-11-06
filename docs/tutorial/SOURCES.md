# Tutorial data sources

The 12 tutorials follow the examples in *Beyond Display*. Their input bundles contain selected real structures, docking poses, derived tables, saved scenes and figures from the accompanying research materials. The completed packages add the claims, evidence links, settings and limitations entered during the illustrated GUI workflow.

Each case below identifies its source system and all imported files. Scientific inputs retain their recorded scope: a structure, a derived measurement and a saved view each contribute a different part of the audit.

## Source records

- **Experimental coordinates:** [RCSB PDB](https://www.rcsb.org/). The cases use the accessioned coordinate files listed below. Cite the corresponding structure records when reusing them.
- **Predicted structure:** [AlphaFold DB model AF-P69441-F1, version 6](https://alphafold.ebi.ac.uk/files/AF-P69441-F1-model_v6.cif), for UniProt P69441.
- **Docking poses and receptor inputs:** Xu and colleagues, [A Multi-Paradigm Benchmark of Molecular Docking: From Physics to Co-folding and Hybrid Models](https://zenodo.org/records/19560204), version v1, 13 April 2026, DOI 10.5281/zenodo.19560204. The official record identifies the GNINA pose archive, Vina/GNINA PDBQT input archive and results tables. It lists the [Creative Commons Attribution 4.0 license](https://creativecommons.org/licenses/by/4.0/).
- **Interaction fingerprints:** Bouysset and Fiorucci, [ProLIF-paper source repository](https://github.com/chemosim-lab/ProLIF-paper), archived as [version 1.0.0](https://zenodo.org/records/4945869), DOI 10.5281/zenodo.4945869. The included pickle comes from repository revision `5d6d22e`. Cite [ProLIF: a library to encode molecular interactions as fingerprints](https://doi.org/10.1186/s13321-021-00548-6).
- **Simulation setup and trajectory-derived tables:** [GPCRmd dynamic 106](https://www.gpcrmd.org/dynadb/dynamics/id/106/), as described by the supplied setup records. The tutorial bundles the selected metadata and derived tables; trajectory replay requires the corresponding topology and trajectory files.
- **Validity-check context:** [PoseBusters](https://doi.org/10.1039/D3SC04185A). Case 4C links the supplied findings and measured close contacts to the selected GNINA pose.

## Attribution and file variants

The ProLIF source repository applies Apache License 2.0 to its files unless a file states otherwise. Its copyright notice is retained here verbatim:

> Copyright 2021 Cédric BOUYSSET

See [the original ProLIF license](licenses/ProLIF-paper-LICENSE.txt). The case 4E downloads also carry this license. Upstream structures and datasets retain their respective source terms; the ClaimTrace software license covers the software.

The file lists below distinguish deposited coordinates and published datasets from author-prepared scenes, figures and derived analyses. Receptor PDBQT files for the docking cases retain the supplied coordinate records and use portable source labels in their `REMARK` headers. The case 1B6 replay script loads the saved PyMOL session. Each download includes its source attribution and applicable upstream license notices.

The flat `files/` folders are prepared for GUI import. Native PyMOL replay uses the folder layout in a completed example package. In case 1B6, run the replay script from that completed package’s root so that its `native/` path resolves.

## Reuse and citation

ClaimTrace-authored tutorial materials follow the repository’s [MIT License](https://github.com/GeraltZeroZhong/ClaimTrace/blob/v1.0/LICENSE). The scientific inputs and their derivatives retain the source terms below:

| Material | Source terms |
|---|---|
| PDB coordinates | [CC0 1.0](https://www.rcsb.org/pages/usage-policy) |
| AlphaFold DB model | [CC BY 4.0](https://alphafold.ebi.ac.uk/assets/License-Disclaimer.pdf) |
| Docking benchmark, Zenodo 19560204 | [CC BY 4.0](https://zenodo.org/records/19560204) |
| GPCRmd data | CC BY 4.0, as stated in the [GPCRmd paper’s Methods](https://discovery.dundee.ac.uk/ws/portalfiles/portal/49547242/49491_2_merged_1590582664_1.pdf) |
| ProLIF-paper files | [Apache License 2.0](licenses/ProLIF-paper-LICENSE.txt) |

Software citation: Zhong S. *ClaimTrace*, version 1.0. [Source repository](https://github.com/GeraltZeroZhong/ClaimTrace). When reusing tutorial inputs or derived results, also cite the corresponding upstream records and publications listed above and retain their attribution and license notices. The per-file descriptions below identify the sources and author-prepared analyses.

## Cases and included inputs

### Figure 1B1 — Adenylate kinase pocket views

Source: [RCSB PDB 1AKE, chain A, ligand AP5.](https://www.rcsb.org/structure/1AKE)

Experimental coordinates; article-authored PyMOL scenes, native sessions and rendered views.

[Open tutorial](cases/f1-b1.html) · [Download inputs](downloads/f1-b1-inputs.zip)

| Imported file | Origin |
|---|---|
| `1_1_occluded_ligand.pml` | Author-prepared PyMOL scene script for adenylate kinase and AP5 in PDB 1AKE. |
| `1_2_buried_pocket_surface.pml` | Author-prepared PyMOL scene script for adenylate kinase and AP5 in PDB 1AKE. |
| `1_1_occluded_ligand.png` | Author-rendered molecular view of adenylate kinase and AP5 in PDB 1AKE. |
| `1_2_buried_pocket_surface.png` | Author-rendered molecular view of adenylate kinase and AP5 in PDB 1AKE. |
| `1_1_occluded_ligand.pse` | Author-saved PyMOL session for adenylate kinase and AP5 in PDB 1AKE. |
| `1_2_buried_pocket_surface.pse` | Author-saved PyMOL session for adenylate kinase and AP5 in PDB 1AKE. |
| `pdb_00001ake.cif.gz` | Experimental coordinates from RCSB PDB 1AKE, in compressed PDBx/mmCIF format. |

### Figure 1B5 — Adenylate kinase domain context

Source: [RCSB PDB 1AKE, chain A, ligand AP5.](https://www.rcsb.org/structure/1AKE)

Experimental coordinates; article-authored overall view, native session and source notes. Domain ranges are recorded with the tutorial interpretation.

[Open tutorial](cases/f1-b5.html) · [Download inputs](downloads/f1-b5-inputs.zip)

| Imported file | Origin |
|---|---|
| `5_1_overall_structure.pml` | Author-prepared PyMOL scene script for adenylate kinase domains in PDB 1AKE. |
| `5_1_overall_structure.png` | Author-rendered molecular view of adenylate kinase domains in PDB 1AKE. |
| `5_1_overall_structure.pse` | Author-saved PyMOL session for adenylate kinase domains in PDB 1AKE. |
| `SOURCES.md` | Source accessions and selection criteria for the adenylate kinase examples. |
| `pdb_00001ake.cif.gz` | Experimental coordinates from RCSB PDB 1AKE, in compressed PDBx/mmCIF format. |

### Figure 1B6 — Alternate camera view

Source: [RCSB PDB 1AKE, chain A, ligand AP5.](https://www.rcsb.org/structure/1AKE)

Experimental coordinates; article-authored alternate view, native session and contact summary; a tutorial-authored replay script loads the native session.

[Open tutorial](cases/f1-b6.html) · [Download inputs](downloads/f1-b6-inputs.zip)

| Imported file | Origin |
|---|---|
| `6_1_interaction_view_alternate.pml` | Author-prepared PyMOL scene script for the alternate AP5 view in PDB 1AKE. |
| `6_1_interaction_view_alternate.png` | Author-rendered molecular view of the alternate AP5 view in PDB 1AKE. |
| `2_1_interaction_view_contacts.json` | Author-calculated contact summary for AP5 and adenylate kinase in PDB 1AKE. |
| `6_1_interaction_view_alternate.pse` | Author-saved PyMOL session for the alternate AP5 view in PDB 1AKE. |
| `pdb_00001ake.cif.gz` | Experimental coordinates from RCSB PDB 1AKE, in compressed PDBx/mmCIF format. |
| `replay-6_1_interaction_view_alternate.pml` | Tutorial-authored native-session loader. Run from the completed package root. |

### Figure 1B2 — Adenylate kinase contacts

Source: [RCSB PDB 1AKE, chain A, ligand AP5.](https://www.rcsb.org/structure/1AKE)

Experimental coordinates; article-authored contact tables, PyMOL scene and contact-map figure. The displayed map and full-protein pair table use different selections.

[Open tutorial](cases/f1-b2.html) · [Download inputs](downloads/f1-b2-inputs.zip)

| Imported file | Origin |
|---|---|
| `2_1_interaction_view.pml` | Author-prepared PyMOL scene script for AP5 contacts in PDB 1AKE. |
| `2_1_interaction_view.png` | Author-rendered molecular view of AP5 contacts in PDB 1AKE. |
| `2_2_residue_contact_map.png` | Author-generated residue contact-map figure for AP5 in PDB 1AKE. |
| `2_1_interaction_view.pse` | Author-saved PyMOL session for AP5 contacts in PDB 1AKE. |
| `2_2_contact_map_residues.csv` | Residue selections used in the author-generated PDB 1AKE contact map. |
| `2_2_contact_map_pairs.csv` | Author-calculated residue contact pairs for PDB 1AKE; the displayed map uses a selected subset. |
| `2_1_interaction_view_contacts.json` | Author-calculated contact summary for AP5 and adenylate kinase in PDB 1AKE. |
| `pdb_00001ake.cif.gz` | Experimental coordinates from RCSB PDB 1AKE, in compressed PDBx/mmCIF format. |

### Figure 4A — BACE1 pocket waters

Source: [RCSB PDB 3UQX and the 20-entry BACE1 selection recorded in bace1_selected_structures.csv.](https://www.rcsb.org/structure/3UQX)

Experimental reference coordinates; article-authored water clustering, alignment and geometric bridge-proxy tables; three recorded visual states.

[Open tutorial](cases/f3-a.html) · [Download inputs](downloads/f3-a-inputs.zip)

| Imported file | Origin |
|---|---|
| `3UQX.pdb` | Experimental coordinates from RCSB PDB 3UQX. |
| `alignment_metadata.csv` | Author-recorded structural alignments for the BACE1 coordinate set listed in bace1_selected_structures.csv. |
| `bace1_selected_structures.csv` | PDB accessions and selection information for the BACE1 water comparison. |
| `case01_real_a1_all_waters.pml` | Author-prepared PyMOL scene script for BACE1 pocket waters in PDB 3UQX. |
| `case01_real_a1_all_waters.png` | Author-rendered molecular view of BACE1 pocket waters in PDB 3UQX. |
| `case01_real_a1_all_waters.pse` | Author-saved PyMOL session for BACE1 pocket waters in PDB 3UQX. |
| `case01_real_a2_retained_waters.pml` | Author-prepared PyMOL scene script for BACE1 pocket waters in PDB 3UQX. |
| `case01_real_a2_retained_waters.png` | Author-rendered molecular view of BACE1 pocket waters in PDB 3UQX. |
| `case01_real_a2_retained_waters.pse` | Author-saved PyMOL session for BACE1 pocket waters in PDB 3UQX. |
| `case01_real_a3_waters_removed.pml` | Author-prepared PyMOL scene script for BACE1 pocket waters in PDB 3UQX. |
| `case01_real_a3_waters_removed.png` | Author-rendered molecular view of BACE1 pocket waters in PDB 3UQX. |
| `case01_real_a3_waters_removed.pse` | Author-saved PyMOL session for BACE1 pocket waters in PDB 3UQX. |
| `water_evidence_summary.json` | Author-derived summary of BACE1 water clusters, retained waters and geometric bridge proxies. |
| `water_evidence_table.csv` | Author-derived BACE1 water positions, cluster assignments and geometric bridge-proxy records. |

The source selection lists `3UQX`, `5HE5`, `4FCO`, `5HD0`, `5HDU`, `4ZPE`, `5HDX`, `4IVT`, `4D88`, `7MYR`, `3TPP`, `3UQU`, `4D89`, `7MYI`, `3VF3`, `5HDZ`, `5HU1`, `4L7G`, `6UVY` and `4R93`. The tutorial carries the reference coordinate file and the selected evidence tables.

### Figure 4C — Close contacts in a docking pose

Source: [A Multi-Paradigm Benchmark of Molecular Docking, Zenodo 19560204; complex 7xbn__1__1.A__1.C_1.D, GNINA rank 3.](https://zenodo.org/records/19560204)

Supplied GNINA SDF pose and benchmark receptor PDBQT; article-authored selected-contact table, scenes and figure. PoseBusters supplies methodological context for the recorded validity findings.

[Open tutorial](cases/f3-c.html) · [Download inputs](downloads/f3-c-inputs.zip)

| Imported file | Origin |
|---|---|
| `case03_real_validity_failure_7xbn_rank3.pml` | Author-prepared PyMOL scene script for GNINA rank 3 of complex 7xbn__1__1.A__1.C_1.D. |
| `case03_real_validity_failure_7xbn_rank3.png` | Author-rendered molecular view of GNINA rank 3 of complex 7xbn__1__1.A__1.C_1.D. |
| `case03_real_validity_failure_7xbn_rank3.png.metadata.json` | Figure-generation and source metadata for GNINA rank 3 of complex 7xbn__1__1.A__1.C_1.D. |
| `case03_real_validity_failure_7xbn_rank3.pse` | Author-saved PyMOL session for GNINA rank 3 of complex 7xbn__1__1.A__1.C_1.D. |
| `case03_selected_close_contacts.csv` | Author-calculated short-contact distances and atom identities for GNINA rank 3 of complex 7xbn__1__1.A__1.C_1.D. |
| `protein.pdbqt` | Receptor PDBQT for complex 7xbn__1__1.A__1.C_1.D from the Multi-Paradigm docking benchmark, Zenodo 19560204. The REMARK header uses a portable source label; coordinate records retain the supplied values. |
| `rank3_score0.63.sdf` | Supplied GNINA rank 3 pose for complex 7xbn__1__1.A__1.C_1.D from the Multi-Paradigm docking benchmark, Zenodo 19560204. |

### Figure 4D — D3 receptor distance and setup

Sources: [RCSB PDB 3PBL](https://www.rcsb.org/structure/3PBL), eticlopride; [GPCRmd dynamic 106](https://www.gpcrmd.org/dynadb/dynamics/id/106/) setup record.

Experimental coordinates; article-authored Asp110 distance view and native session; GPCRmd setup and system-count tables.

[Open tutorial](cases/f3-d.html) · [Download inputs](downloads/f3-d-inputs.zip)

| Imported file | Origin |
|---|---|
| `3PBL.pdb` | Experimental coordinates from RCSB PDB 3PBL. |
| `case04_real_3pbl_eticlopride_asp110.pml` | Author-prepared PyMOL scene script for Asp110 and eticlopride in PDB 3PBL. |
| `case04_real_3pbl_eticlopride_asp110.png` | Author-rendered molecular view of Asp110 and eticlopride in PDB 3PBL. |
| `case04_real_3pbl_eticlopride_asp110.pse` | Author-saved PyMOL session for Asp110 and eticlopride in PDB 3PBL. |
| `gpcrmd_dyn106_setup_metadata.csv` | Simulation setup information for GPCRmd dynamic 106, separate from the PDB 3PBL crystal structure. |
| `gpcrmd_dyn106_system_counts.csv` | System composition for GPCRmd dynamic 106, with residue and atom counts. |

### Figure 1B3 — Confidence and backbone geometry

Source: [AlphaFold DB AF-P69441-F1, model v6; UniProt P69441.](https://alphafold.ebi.ac.uk/files/AF-P69441-F1-model_v6.cif)

Predicted coordinates; article-authored pLDDT view and cctbx/MolProbity Ramachandran results. The geometry table covers the AlphaFold model.

[Open tutorial](cases/f1-b3.html) · [Download inputs](downloads/f1-b3-inputs.zip)

| Imported file | Origin |
|---|---|
| `3_1_alphafold_plddt.pml` | Author-prepared PyMOL scene script for AlphaFold model AF-P69441-F1 v6. |
| `3_1_alphafold_plddt.png` | Author-rendered molecular view of AlphaFold model AF-P69441-F1 v6. |
| `3_2_ramachandran_general.png` | Author-generated Ramachandran plot from cctbx/MolProbity analysis of AlphaFold model AF-P69441-F1 v6. |
| `3_2_ramachandran.csv` | Residue-level backbone geometry results from cctbx/MolProbity analysis of AlphaFold model AF-P69441-F1 v6. |
| `3_1_alphafold_plddt.pse` | Author-saved PyMOL session for AlphaFold model AF-P69441-F1 v6. |
| `3_2_ramachandran.json` | Backbone geometry results and summary from cctbx/MolProbity analysis of AlphaFold model AF-P69441-F1 v6. |
| `AF-P69441-F1-model_v6.cif` | AlphaFold DB predicted coordinates for UniProt P69441, model AF-P69441-F1 v6. |

### Figure 1B4 — AP5 structural ensemble

Source: [Sixteen RCSB PDB structures selected using UniProt P69441 and chemical component AP5.](https://www.rcsb.org/)

Experimental coordinates; article-authored alignment, PCA, assignments, representatives and figures. The 30 selected AP5 instances support a descriptive structural comparison.

[Open tutorial](cases/f1-b4.html) · [Download inputs](downloads/f1-b4-inputs.zip)

| Imported file | Origin |
|---|---|
| `4_1_ap5_conformational_landscape.png` | Author-generated landscape for the aligned AP5 structural ensemble. |
| `4_2_ap5_representative_states.png` | Author-generated comparison of representative AP5 conformations from the selected PDB structures. |
| `4_1_ap5_conformational_landscape.csv` | Author-calculated principal-component coordinates, density estimates and basin assignments for the AP5 landscape. |
| `B4_PROVENANCE.json` | Selection criteria, common atoms, alignment, representation and principal-component analysis settings for the AP5 ensemble. |
| `4_1_ap5_conformational_landscape.json` | Author-recorded analysis metadata for the AP5 conformational landscape. |
| `ap5_instance_assignments.csv` | Author-derived AP5 instance assignments, principal-component coordinates and alignment results, with PDB and chain identities. |
| `ap5_pca_explained_variance.csv` | Explained-variance ratios from the principal-component analysis of aligned AP5 coordinates. |
| `ap5_representative_states.csv` | Author-selected representative AP5 instances with cluster populations and PDB identities. |
| `common_ap5_atom_names.json` | Shared AP5 heavy-atom names used to compare the selected structural instances. |
| `pdb_00001ake.cif.gz` | Experimental coordinates from RCSB PDB 1AKE, in compressed PDBx/mmCIF format. |
| `pdb_00001e4v.cif.gz` | Experimental coordinates from RCSB PDB 1E4V, in compressed PDBx/mmCIF format. |
| `pdb_00001e4y.cif.gz` | Experimental coordinates from RCSB PDB 1E4Y, in compressed PDBx/mmCIF format. |
| `pdb_00003hpq.cif.gz` | Experimental coordinates from RCSB PDB 3HPQ, in compressed PDBx/mmCIF format. |
| `pdb_00003hpr.cif.gz` | Experimental coordinates from RCSB PDB 3HPR, in compressed PDBx/mmCIF format. |
| `pdb_00004x8l.cif.gz` | Experimental coordinates from RCSB PDB 4X8L, in compressed PDBx/mmCIF format. |
| `pdb_00004x8o.cif.gz` | Experimental coordinates from RCSB PDB 4X8O, in compressed PDBx/mmCIF format. |
| `pdb_00005eje.cif.gz` | Experimental coordinates from RCSB PDB 5EJE, in compressed PDBx/mmCIF format. |
| `pdb_00006ham.cif.gz` | Experimental coordinates from RCSB PDB 6HAM, in compressed PDBx/mmCIF format. |
| `pdb_00006hap.cif.gz` | Experimental coordinates from RCSB PDB 6HAP, in compressed PDBx/mmCIF format. |
| `pdb_00008bqf.cif.gz` | Experimental coordinates from RCSB PDB 8BQF, in compressed PDBx/mmCIF format. |
| `pdb_00008pvw.cif.gz` | Experimental coordinates from RCSB PDB 8PVW, in compressed PDBx/mmCIF format. |
| `pdb_00008q2b.cif.gz` | Experimental coordinates from RCSB PDB 8Q2B, in compressed PDBx/mmCIF format. |
| `pdb_00009l14.cif.gz` | Experimental coordinates from RCSB PDB 9L14, in compressed PDBx/mmCIF format. |
| `pdb_00009r6u.cif.gz` | Experimental coordinates from RCSB PDB 9R6U, in compressed PDBx/mmCIF format. |
| `pdb_00009r71.cif.gz` | Experimental coordinates from RCSB PDB 9R71, in compressed PDBx/mmCIF format. |

Included PDB entries: `1AKE`, `1E4V`, `1E4Y`, `3HPQ`, `3HPR`, `4X8L`, `4X8O`, `5EJE`, `6HAM`, `6HAP`, `8BQF`, `8PVW`, `8Q2B`, `9L14`, `9R6U` and `9R71`. The saved density-derived landscape remains an exploratory display of this structural sample.

### Figure 4B — GNINA pose comparison

Source: [A Multi-Paradigm Benchmark of Molecular Docking, Zenodo 19560204; complex 7r26__1__1.A__1.B.](https://zenodo.org/records/19560204)

Five supplied GNINA SDF poses and the benchmark receptor PDBQT; article-authored comparison table, scenes and figure. Reference RMSDs are supplied benchmark results.

[Open tutorial](cases/f3-b.html) · [Download inputs](downloads/f3-b-inputs.zip)

| Imported file | Origin |
|---|---|
| `case02_pose_evidence_augmented.csv` | Author-prepared comparison combining supplied GNINA scores and reference RMSDs with contact and pocket-occupancy summaries for complex 7r26__1__1.A__1.B. |
| `case02_real_gnina_pose_ensemble_7r26.pml` | Author-prepared PyMOL scene script for the five GNINA poses of complex 7r26__1__1.A__1.B. |
| `case02_real_gnina_pose_ensemble_7r26.png` | Author-rendered molecular view of the five GNINA poses of complex 7r26__1__1.A__1.B. |
| `case02_real_gnina_pose_ensemble_7r26.png.metadata.json` | Figure-generation and source metadata for the five GNINA poses of complex 7r26__1__1.A__1.B. |
| `case02_real_gnina_pose_ensemble_7r26.pse` | Author-saved PyMOL session for the five GNINA poses of complex 7r26__1__1.A__1.B. |
| `protein.pdbqt` | Receptor PDBQT for complex 7r26__1__1.A__1.B from the Multi-Paradigm docking benchmark, Zenodo 19560204. The REMARK header uses a portable source label; coordinate records retain the supplied values. |
| `rank1_score1.00.sdf` | Supplied GNINA rank 1 pose for complex 7r26__1__1.A__1.B from the Multi-Paradigm docking benchmark, Zenodo 19560204. |
| `rank2_score1.00.sdf` | Supplied GNINA rank 2 pose for complex 7r26__1__1.A__1.B from the Multi-Paradigm docking benchmark, Zenodo 19560204. |
| `rank3_score0.91.sdf` | Supplied GNINA rank 3 pose for complex 7r26__1__1.A__1.B from the Multi-Paradigm docking benchmark, Zenodo 19560204. |
| `rank4_score0.85.sdf` | Supplied GNINA rank 4 pose for complex 7r26__1__1.A__1.B from the Multi-Paradigm docking benchmark, Zenodo 19560204. |
| `rank5_score0.82.sdf` | Supplied GNINA rank 5 pose for complex 7r26__1__1.A__1.B from the Multi-Paradigm docking benchmark, Zenodo 19560204. |

### Figure 4E — ProLIF interaction events

Source: [chemosim-lab/ProLIF-paper v1.0.0, Zenodo 4945869, repository revision 5d6d22e; 5-HT1B–ergotamine example.](https://zenodo.org/records/4945869)

Original precomputed Notebooks/pickles/ifp_df.pkl; article-authored event matrix, transition table and figure.

[Open tutorial](cases/f3-e.html) · [Download inputs](downloads/f3-e-inputs.zip)

| Imported file | Origin |
|---|---|
| `case05_real_prolif_event_matrix.csv` | Author-derived interaction-state matrix from the ProLIF-paper 5-HT1B–ergotamine fingerprints. |
| `case05_real_prolif_event_transitions.csv` | Author-derived interaction transition events from the ProLIF-paper 5-HT1B–ergotamine fingerprints. |
| `case05a_publication_prolif_event_map.png` | Author-generated interaction-state and transition-event figure for the ProLIF-paper 5-HT1B–ergotamine example. |
| `ifp_df.pkl` | Precomputed 5-HT1B–ergotamine interaction fingerprints from ProLIF-paper v1.0.0, Notebooks/pickles/ifp_df.pkl (repository revision 5d6d22e). |

### Figure 4F — D3 receptor replicate summary

Source: [GPCRmd dynamic 106, dopamine D3 receptor–eticlopride.](https://www.gpcrmd.org/dynadb/dynamics/id/106/)

Article-authored summaries derived from three GPCRmd trajectories: distance, RMSD, interaction events, residue contacts and the summary figure.

[Open tutorial](cases/f3-f.html) · [Download inputs](downloads/f3-f-inputs.zip)

| Imported file | Origin |
|---|---|
| `case05b_publication_gpcrmd_d3r_event_summary.png` | Author-generated distance, RMSD and contact comparison for three GPCRmd dynamic 106 replicates. |
| `d3r_eticlopride_gpcrmd_events_combined.csv` | Author-calculated per-frame Asp110–eticlopride distances and ligand RMSDs for three GPCRmd dynamic 106 replicates. |
| `d3r_eticlopride_gpcrmd_summary.csv` | Author-calculated replicate summaries of Asp110–eticlopride proximity, distance and ligand RMSD for GPCRmd dynamic 106. |
| `d3r_eticlopride_residue_contact_summary.csv` | Author-calculated residue contact summaries and transition counts for GPCRmd dynamic 106. |
| `d3r_eticlopride_residue_contacts_combined.csv` | Author-calculated time-resolved residue–ligand distances and contact states for GPCRmd dynamic 106. |
