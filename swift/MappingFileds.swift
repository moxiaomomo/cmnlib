import Foundation
import AppKit
import Vision

struct LocaleMapping: Codable {
    let cn: String
    let tc: String
    let en: String
}

struct FoodCategory: Codable {
    let cateId: Int
    let cateName: String
    let faCateName: String
    let cateNameTC: String
    let faCateNameTC: String
    let cateNameEN: String
    let faCateNameEN: String

    enum CodingKeys: String, CodingKey {
        case cateId = "cid"
        case cateName = "cname"
        case faCateName = "fcname"
        case cateNameTC = "cname_tc"
        case faCateNameTC = "fcname_tc"
        case cateNameEN = "cname_en"
        case faCateNameEN = "fcname_en"
    }
}

struct FoodNutrition: Codable, Identifiable {
    let id: Int
    let name: String
//    let categoryName: String
    let categoryId: Int
//    let fatherId: Int
//    let fatherCategoryName: String
    let aliasName: String?
    let englishName: String?
    let ediblePart: Double?
    
    // 营养字段 —— 因为 Python 可能转为数值，这里统一用 Double?，
    // 对于极少数保留字符串的字段（如 "b1" 等）会解码失败，所以全部改为 String? 最稳妥。
    // 这里采用折中：所有营养值用 String?，后续使用时再解析数值。
    // 若想直接得到数值，需要保证 Python 只输出数字，Swift 改用 Double?。
    let water: Double?
    let energy: Double?
    let protein: Double?
    let fat: Double?
    let cholesterol: Double?
    let ash: Double?
    let carbohydrate: Double?
    let dietaryFiber: Double?
    let carotene: Double?
    let vitaminA: Double?
    let vitaminE: Double?
    let thiamin: Double?
    let riboflavin: Double?
    let niacin: Double?
    let vitaminC: Double?
    let calcium: Double?
    let phosphorus: Double?
    let potassium: Double?
    let sodium: Double?
    let magnesium: Double?
    let iron: Double?
    let zinc: Double?
    let selenium: Double?
    let copper: Double?
    let manganese: Double?
    let iodine: Double?
    let sfa: Double?
    let mufa: Double?
    let pufa: Double?
    let fattyAcidsTotal: Double?

    // 映射短键名
    enum CodingKeys: String, CodingKey {
        case id = "i"
        case name = "n"
//        case categoryName = "cn"
        case categoryId = "ci"
//        case fatherId = "fi"
//        case fatherCategoryName = "fn"
        case aliasName = "a"
        case englishName = "en"
        case ediblePart = "ep"
        case water = "w"
        case energy = "e"
        case protein = "p"
        case fat = "f"
        case cholesterol = "chol"
        case ash = "ash"
        case carbohydrate = "carb"
        case dietaryFiber = "fib"
        case carotene = "car"
        case vitaminA = "va"
        case vitaminE = "ve"
        case thiamin = "b1"
        case riboflavin = "b2"
        case niacin = "b3"
        case vitaminC = "vc"
        case calcium = "ca"
        case phosphorus = "ph"
        case potassium = "k"
        case sodium = "na"
        case magnesium = "mg"
        case iron = "fe"
        case zinc = "zn"
        case selenium = "se"
        case copper = "cu"
        case manganese = "mn"
        case iodine = "i2"
        case sfa = "sfa"
        case mufa = "mufa"
        case pufa = "pufa"
        case fattyAcidsTotal = "fat"
    }
}

func main() {
    let jsonCoder = JSONDecoder()
    guard let rawData = try? Data(contentsOf: URL(fileURLWithPath: "./food_nutrition.json")) else {
        print("Failed to read JSON file.")
        return
    }
    let foodNutritionList = try? jsonCoder.decode([FoodNutrition].self, from: rawData)
    print(foodNutritionList?.first)
}

main()