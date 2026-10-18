package dev.eggmasonvalue.tracky.core.data

import androidx.room.TypeConverter

class TrackyTypeConverters {
    @TypeConverter
    fun dispositionToStorage(value: ImportDisposition?): String? = value?.name

    @TypeConverter
    fun storageToDisposition(value: String?): ImportDisposition? =
        value?.let(ImportDisposition::valueOf)
}
