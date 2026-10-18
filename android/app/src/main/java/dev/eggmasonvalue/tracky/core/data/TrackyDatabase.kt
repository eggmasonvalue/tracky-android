package dev.eggmasonvalue.tracky.core.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters

@Database(
    entities = [ImportLedgerEntity::class, SyncStateEntity::class],
    version = 2,
    exportSchema = true,
)
@TypeConverters(TrackyTypeConverters::class)
abstract class TrackyDatabase : RoomDatabase() {
    internal abstract fun trackyDao(): TrackyDao

    companion object {
        const val DATABASE_NAME: String = "tracky-import-ledger.db"

        fun build(context: Context): TrackyDatabase =
            Room.databaseBuilder(
                context.applicationContext,
                TrackyDatabase::class.java,
                DATABASE_NAME,
            ).build()
    }
}
