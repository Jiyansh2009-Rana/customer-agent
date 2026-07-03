import os
from typing import List, Optional, Literal 
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from pyairtable import Api
from pyairtable.formulas import match
from groq import Groq
import json
from datetime import date
import uvicorn





load_dotenv()



AIRTABLE_PAT = os.getenv("AIRTABLE_PAT")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

api = Api(AIRTABLE_PAT)
Database = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)
groq_client = Groq(api_key=GROQ_API_KEY)

app = FastAPI()

class Base_items(BaseModel):
    Name : str
    E_mail : EmailStr  
    mobile_no : str
    Date : date
    amount : float
    Buying_products : str
    ordered_stutas : Literal["Delivered", "Panding"]
    
    

class create_item(Base_items):
    pass
    

class update_item(BaseModel):
    Name : Optional[str] = None
    mobile_no : Optional[str] = None
    Date : Optional[date] = None
    amount : Optional[float] = None
    Buying_products : Optional[str] = None
    ordered_stutas : Optional[Literal["Delivered", "Panding"]] = None
    
def get_record(E_mail: EmailStr , Name : str):
    
    formula= match ({ "E_mail" : E_mail ,
    "Name" : Name})
    record = Database.first(formula=formula)
    if not record:
        raise HTTPException(status_code=404, detail=f"No record found with email : {E_mail} and Name : {Name}")
    return record
    



def format_record(record):
    
    
    return {
        "id": record["id"],
        **record["fields"]
    }



def get_all_record():
    records = Database.all()
    
    return [format_record(record) for record in records]



def record_by_email_name(email: EmailStr , Name : str):
    
    
    record = get_record(email,Name)
    
    return format_record(record)

    
def create_item_fun(item: create_item):
    
    formula = match({"email": item.E_mail})
    if Database.first(formula=formula):
        raise HTTPException(status_code=400, detail="Email or Customer already exists")
    
    new_record = Database.create(item.model_dump())
    
    return format_record(new_record) 
                            
 
def update_existing_record(email: str, name : str, item_update: update_item):
          
          
         record = record_by_email_name(email,name)
         
         updates = item_update.model_dump(
        exclude_unset=True
    )

         if not updates:
             
            raise HTTPException(
                status_code=400,
                detail="No fields provided for update"
        )

         updated_record = Database.update(
            record["id"],
            updates
        )
        
         return format_record(updated_record)

def delete_item_by_email(email: EmailStr , name ):

    record = record_by_email_name(email,name)
    
    Database.delete(record["id"])

    return {
        "message": f"Order of  {name} is  cancelled"
    }
    
    

tools = [
  {
    "type": "function",
    "function": {
      "name": "get_all_record",
      "description": "Retrieves all formatted records currently stored in the database.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "record_by_email_name",
      "description": "Retrieves a specific formatted record using the provided email address and name.",
      "parameters": {
        "type": "object",
        "properties": {
          "email": {
            "type": "string",
            "format": "email",
            "description": "The email address associated with the record."
          },
          "Name": {
            "type": "string",
            "description": "The name associated with the record."
          }
        },
        "required": ["email", "Name"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "create_item_fun",
      "description": "Creates a new record after verifying that the email or customer does not already exist.",
      "parameters": {
        "type": "object",
        "properties": {
          "item": {
            "type": "object",
            "description": "The data object required to create a new record.",
            "properties": {
              "E_mail": {
                "type": "string",
                "format": "email",
                "description": "The email address for the new record."
              }
            },
            "required": ["E_mail"],
            "additionalProperties": True
          }
        },
        "required": ["item"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "update_existing_record",
      "description": "Updates fields of an existing record identified by email and name. Raises an error if no fields are provided for modification.",
      "parameters": {
        "type": "object",
        "properties": {
          "email": {
            "type": "string",
            "format": "email",
            "description": "The email address of the record to update."
          },
          "name": {
            "type": "string",
            "description": "The name of the record to update."
          },
          "item_update": {
            "type": "object",
            "description": "The fields containing the updates to be applied.",
            "properties": {},
            "additionalProperties": True
          }
        },
        "required": ["email", "name", "item_update"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "delete_item_by_email",
      "description": "Deletes/cancels an existing record or order using the associated email and name.",
      "parameters": {
        "type": "object",
        "properties": {
          "email": {
            "type": "string",
            "format": "email",
            "description": "The email address associated with the record to delete."
          },
          "name": {
            "type": "string",
            "description": "The name associated with the record to delete."
          }
        },
        "required": ["email", "name"]
      }
    }
  }
]

@app.post("/your_Bussiness_agent")
def llm_agent(user_prompt: str):
    messages = [
        {"role": "system", "content": "You are a helpful AI assistant. When using tools, ONLY call them using the provided function schema. Do NOT generate text like <function=...>. If unsure, respond normally."},
        {"role": "user", "content": user_prompt}
    ]
    
    try:
        completion = groq_client.chat.completions.create(  
            model="qwen/qwen3.6-27b",  
            messages=messages,  
            tools=tools,  
            tool_choice="auto",  
        )  
    except Exception as e:
        return f"API Error: {str(e)}"  

    if completion is None:
        return "Error: No response from API"  
        
    response_message = completion.choices[0].message  
    tool_calls = response_message.tool_calls
    
    if not tool_calls:
        return {"response": response_message.content}
    
    messages.append(response_message)
    
    for tool_call in tool_calls:
        function_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)
        result = None
        
        try:
            if function_name == "get_all_record":
                result = get_all_record()
                
            elif function_name == "record_by_email_name":
                result = record_by_email_name(
                    email=arguments.get("email"), 
                    Name=arguments.get("Name")
                )
            
            elif function_name == "create_item_fun":
                item_data = create_item(**arguments.get("item", {}))
                result = create_item_fun(item=item_data)
        
            elif function_name == "update_existing_record":
                update_data = update_item(**arguments.get("item_update", {}))
                result = update_existing_record(
                    email=arguments.get("email"),
                    name=arguments.get("name"),
                    item_update=update_data
                )  
            
            elif function_name == "delete_item_by_email":
                result = delete_item_by_email(
                    email=arguments.get("email"),
                    name=arguments.get("name")
                )
            
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": function_name,
                "content": json.dumps(result)
            })
            
        except Exception as tool_error:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": function_name,
                "content": json.dumps({"error": str(tool_error)})
            })

    try:
        final_completion = groq_client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=messages
        )
        return {"response": final_completion.choices[0].message.content}
    except Exception as e:
        return f"API Error compiling final response: {str(e)}"

    
            
if __name__ == "__main__"    :
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
            