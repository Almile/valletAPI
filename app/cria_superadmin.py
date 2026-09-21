from core.firebase import db

superadmin_uid = "d6WiIEIrJfUCe8cGKOoRAQA6sfo2"

doc_ref = db.collection("usuario").document(superadmin_uid)
doc_ref.set({
    "uid": superadmin_uid,
    "nome": "Super Admin",
    "email": "superadmin@gmail.com",
    "tipo_user": "superadmin",
    "cnh": "",
    "telefone": "",
    "fotoPerfil": "",
    "cargo": "Administrador Geral"
}, merge=True)

print("Superadmin criado com sucesso no Firestore!")