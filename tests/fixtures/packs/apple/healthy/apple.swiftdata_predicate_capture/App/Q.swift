import SwiftData
let uid = userId
let p = #Predicate<Item> { $0.owner == uid }
