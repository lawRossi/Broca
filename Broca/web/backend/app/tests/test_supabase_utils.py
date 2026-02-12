import pytest

from app.utils.supabase_utils import *


def test_get_supabase_client():
    supabase_client = get_supabase_client()
    assert isinstance(supabase_client, Client)


def test_get_s3_client():
    s3_client = get_s3_client()
    assert s3_client is not None
    print(s3_client)


def test_get_supbase():
    supabase = get_supbase()
    assert isinstance(supabase, SupabaseDep)
    assert isinstance(supabase.auth, SupabaseAuth)
    assert isinstance(supabase.client, Client)
    assert isinstance(supabase.db, SupabaseDB)
    assert isinstance(supabase.storage, SupabaseStorage)


@pytest.mark.asyncio
async def test_supabase_db():
    supabase_db = SupabaseDB(get_supabase_client())
    assert isinstance(supabase_db, SupabaseDB)

    result = await supabase_db.select("user_profile")
    assert isinstance(result, list)
    assert len(result) == 2

    result = await supabase_db.select("user_profile", limit=1)
    assert isinstance(result, list)
    assert len(result) == 1

    result = await supabase_db.select("user_profile", columns="id,name")
    assert isinstance(result, list)
    assert len(result[0]) == 2


@pytest.mark.asyncio
async def test_supabase_storage():
    supabase_storage = SupabaseStorage(get_supabase_client())
    assert isinstance(supabase_storage, SupabaseStorage)

    result = await supabase_storage.generate_filename("test.txt")
    assert isinstance(result, str)
    assert result.endswith(".txt")

    result = await supabase_storage.list_files("images")
    assert isinstance(result, list)
    assert len(result) > 0

    result = await supabase_storage.list_files("images", limit=1)
    assert isinstance(result, list)
    assert len(result) == 1
